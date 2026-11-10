"""The ETS analysis's inner loops on a CUDA device, through pycuda.

The same functions as `dsp`, with the same signatures and results, so
`tests/test_dsp_cuda.py` holds each one to its numpy twin. Selected by
`DUE_DSP=cuda`; `dsp` rebinds its functions to these when it is.

The kernels are compiled at first use with the system `nvcc`, for the device's
own compute capability, with fused multiply-add off so the phase arithmetic
rounds as the numpy code's separate multiply and add do. Measured, it makes no
difference: 0 of 20 M bin indices differ with it on or off, because a one-ulp
change moves a sample only if it sits within that of a bin edge. It is kept for
bit-identity, not because a test can tell it from the default.

Sums of ADC codes are exact in float64 whatever the order they are added in, so
the bin means equal numpy's.
"""
import numpy as np

_state = {}

_SOURCE = r"""
extern "C" {

__device__ void add_double(double *address, double value) {
    unsigned long long *a = (unsigned long long *)address;
    unsigned long long old = *a, assumed;
    do {
        assumed = old;
        old = atomicCAS(a, assumed, __double_as_longlong(value + __longlong_as_double(assumed)));
    } while (assumed != old);
}

/* The fold bin of each sample from its segment's start phase and slope. */
__global__ void phase_idx(const double *p0, const double *dp, long long n, int segment,
                          double period, double k, long long nb, long long *out) {
    long long i = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    long long stride = (long long)gridDim.x * blockDim.x;
    for (; i < n; i += stride) {
        long long seg = i / segment;
        long long m = i - seg * segment;
        double u = fmod(p0[seg] + dp[seg] * (double)m, period);
        if (u < 0) u += period;
        out[i] = ((long long)(u * k)) % nb;
    }
}

/* Sum and count of the samples in each bin. */
__global__ void bin_acc(const double *v, const long long *idx, long long n,
                        double *sum, unsigned int *cnt) {
    long long i = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    long long stride = (long long)gridDim.x * blockDim.x;
    for (; i < n; i += stride) {
        add_double(&sum[idx[i]], v[i]);
        atomicAdd(&cnt[idx[i]], 1u);
    }
}

/* One block per phase: sum over the window of tmpl[(x + phi) mod period] * w. */
__global__ void corr(const double *w, const double *x, int n, const double *tmpl, double period,
                     const double *phis, double *out) {
    __shared__ double part[256];
    double phi = phis[blockIdx.x];
    double s = 0.0;
    for (int i = threadIdx.x; i < n; i += blockDim.x) {
        double u = fmod(x[i] + phi, period);
        if (u < 0) u += period;
        s += tmpl[(long long)u] * w[i];
    }
    part[threadIdx.x] = s;
    __syncthreads();
    for (int h = blockDim.x / 2; h > 0; h >>= 1) {
        if (threadIdx.x < h) part[threadIdx.x] += part[threadIdx.x + h];
        __syncthreads();
    }
    if (threadIdx.x == 0) out[blockIdx.x] = part[0];
}

}
"""


def _init():
    if _state:
        return _state
    import pycuda.autoinit  # noqa: F401  (creates the context)
    import pycuda.driver as drv
    from pycuda.compiler import SourceModule
    dev = pycuda.autoinit.device
    major, minor = dev.compute_capability()
    mod = SourceModule(_SOURCE, no_extern_c=True, arch="sm_%d%d" % (major, minor),
                       options=["--fmad=false"])
    _state.update(drv=drv, dev=dev, mod=mod, tmpl={}, name=dev.name(),
                  mem=dev.total_memory())
    return _state


def device_name():
    return _init()["name"]


def _grid(n, block=256, cap=4096):
    return (min(cap, max(1, (n + block - 1) // block)), 1)


def phase_indices(n, rc_adc, phase_at, period, k=1, start=0, segment=2048):
    """The fold bin of each of `n` samples on a fitted phase curve."""
    s = _init()
    drv = s["drv"]
    nseg = (n + segment - 1) // segment
    p0 = np.empty(nseg)
    dp = np.empty(nseg)
    for g in range(nseg):
        i = g * segment
        m = min(segment, n - i)
        x0 = (start + i) * rc_adc
        x1 = (start + i + m) * rc_adc
        p0[g] = x0 + phase_at(x0)
        dp[g] = (x1 + phase_at(x1) - p0[g]) / m
    out = np.empty(n, dtype=np.int64)
    d_out = drv.mem_alloc(out.nbytes)
    s["mod"].get_function("phase_idx")(
        drv.In(p0), drv.In(dp), np.int64(n), np.int32(segment), np.float64(period),
        np.float64(k), np.int64(period * k), d_out, block=(256, 1, 1), grid=_grid(n))
    drv.memcpy_dtoh(out, d_out)
    d_out.free()
    return out


def fold_warped(vals, idx, nb):
    """The mean per bin given each sample's bin; `(curve, counts)`."""
    s = _init()
    drv = s["drv"]
    v = np.ascontiguousarray(vals, dtype=np.float64)
    ix = np.ascontiguousarray(idx, dtype=np.int64)
    n = len(v)
    acc = np.zeros(nb, dtype=np.float64)
    cnt = np.zeros(nb, dtype=np.uint32)
    d_acc, d_cnt = drv.to_device(acc), drv.to_device(cnt)
    d_v, d_ix = drv.to_device(v), drv.to_device(ix)
    s["mod"].get_function("bin_acc")(d_v, d_ix, np.int64(n), d_acc, d_cnt,
                                     block=(256, 1, 1), grid=_grid(n))
    drv.memcpy_dtoh(acc, d_acc)
    drv.memcpy_dtoh(cnt, d_cnt)
    for d in (d_acc, d_cnt, d_v, d_ix):
        d.free()
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = acc / cnt
    counts = cnt.astype(np.int64).tolist()
    return [None if c == 0 else m for m, c in zip(mean.tolist(), counts)], counts


def _template(tmpl):
    """The template on the device, copied once per template object."""
    s = _init()
    key = id(tmpl)
    held = s["tmpl"].get(key)
    if held is not None and held[0] is tmpl:
        return held[1]
    for _, old in s["tmpl"].values():
        old.free()
    s["tmpl"].clear()
    dev = s["drv"].to_device(np.ascontiguousarray(tmpl, dtype=np.float64))
    s["tmpl"][key] = (tmpl, dev)
    return dev


def corr_many(win, xs, tmpl, period, phis):
    """`sum(win * tmpl[int((xs + phi) % period)])` for each phase in `phis`."""
    s = _init()
    drv = s["drv"]
    w = np.ascontiguousarray(win, dtype=np.float64)
    x = np.ascontiguousarray(xs, dtype=np.float64)
    ph = np.ascontiguousarray(phis, dtype=np.float64)
    out = np.empty(len(ph), dtype=np.float64)
    d_out = drv.mem_alloc(out.nbytes)
    s["mod"].get_function("corr")(
        drv.In(w), drv.In(x), np.int32(len(w)), _template(tmpl), np.float64(period),
        drv.In(ph), d_out, block=(256, 1, 1), grid=(len(ph), 1))
    drv.memcpy_dtoh(out, d_out)
    d_out.free()
    return out.tolist()


EXPORTS = ("phase_indices", "fold_warped", "corr_many")
