/*
 * Phase 0 probe: is one source file compilable by both builds?
 *
 * Nothing here is meant to survive. It exists to answer the question
 * every later phase depends on - whether arduino-cli can consume source
 * from outside the sketch folder as a library, so the wire contract can
 * live in one place instead of being hand-copied per track.
 */
#ifndef SHARED_PROBE_H
#define SHARED_PROBE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SHARED_PROBE_MAGIC 0x5EEDBEEFu

uint32_t shared_probe_magic(void);

#ifdef __cplusplus
}
#endif
#endif /* SHARED_PROBE_H */
