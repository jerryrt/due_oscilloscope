"""pcbkit.proof, fab, render, ibom and pinlabels on boards built in the test. Each check is broken on purpose: the mutation must be seen."""
import os, sys, stat, textwrap, zipfile, types
import numpy as np
import pytest
from synth_board import build
from pcbkit import proof, fab, render, ibom, pinlabels

pcbnew = pytest.mark.pcbnew


# ------------------------------------------------------------------------------------------------ proof
@pcbnew
def test_proof_is_equal_for_the_same_board_and_names_each_category_that_moved(tmp_path, pcbnew_mod):
    base = proof.digest(build(tmp_path / 'a.kicad_pcb', zone=True))
    assert proof.compare(base, proof.digest(build(tmp_path / 'a2.kicad_pcb', zone=True))) == []
    assert 'footprints' in proof.compare(base, proof.digest(build(tmp_path / 'f.kicad_pcb', dx=0.1, zone=True)))
    assert 'pads' in proof.compare(base, proof.digest(build(tmp_path / 'f2.kicad_pcb', dx=0.1, zone=True)))
    assert proof.compare(base, proof.digest(build(tmp_path / 't.kicad_pcb', track_dx=0.05, zone=True))) == ['tracks']
    assert proof.compare(base, proof.digest(build(tmp_path / 'v.kicad_pcb', drill=0.35, zone=True))) == ['vias']
    assert proof.compare(base, proof.digest(build(tmp_path / 'z.kicad_pcb', zone_dx=0.5, zone=True))) == ['zones']
    assert proof.compare(base, proof.digest(build(tmp_path / 'nz.kicad_pcb', zone=False))) == ['zones']          # a zone gone


@pcbnew
def test_proof_does_not_see_silk_and_netdiff_sees_a_pad_net(tmp_path, pcbnew_mod):
    a = build(tmp_path / 'a.kicad_pcb')
    s = build(tmp_path / 's.kicad_pcb', text_dx=3.0)
    assert proof.compare(proof.digest(a), proof.digest(s)) == [] and proof.netdiff(a, s) == []                # silk may move
    n = build(tmp_path / 'n.kicad_pcb', sig_net_on_pin2=True)
    d = proof.netdiff(a, n)
    assert len(d) == 2 and any('R1.1' in x for x in d)
    assert proof.compare(proof.digest(a), proof.digest(n)) == ['pads']                                # the digest sees a pad's net too
    assert proof.main([a, s]) == 0 and proof.main([a, n]) == 1


# ------------------------------------------------------------------------------------------------ fab
def test_fab_checks_members_outline_and_drills():
    ident = 'X-REVA'
    names = fab.expected_members(ident)
    assert fab.check_members(names, ident) == []
    assert fab.check_members(names[1:], ident) == ['missing ' + names[0]]
    assert fab.check_members(names + ['junk'], ident) == ['unexpected junk']
    g = '%FSLAX46Y46*%\n%MOMM*%\nX0Y0D02*\nX40000000Y0D01*\nX40000000Y30000000D01*\nX0Y30000000D01*\n'
    assert fab.outline_size(g) == (40.0, 30.0) and fab.check_outline(g, 40, 30) == [] and fab.check_outline(g, 40, 31)
    drl = 'T1C0.300\nT1\nX1.0Y2.0\nX3.0Y4.0\nT2C0.8\nT2\nX1Y1G85X2Y1\n'
    assert fab.drill_hits(drl) == {(0.3, 'round'): 2, (0.8, 'slot'): 1}
    board = '\n\t(footprint "F"\n\t\t(pad "1" thru_hole circle\n\t\t\t(drill 0.3)\n\t\t)\n\t)\n\t(via\n\t\t(drill 0.3)\n\t)\n'
    assert fab.board_holes(board)[0] == {(0.3, 'round'): 2}
    assert fab.check_drills('T1C0.300\nT1\nX1.0Y2.0\nX3.0Y4.0\n', '', board) == []
    assert fab.check_drills('T1C0.300\nT1\nX1.0Y2.0\n', '', board)                                    # a hole missing in the drill file
    stamp = fab._norm(b'G04 plot 2024-05-06T07:08:09+00:00*\n')
    assert b'2000-01-01T00:00:00+00:00' in stamp and b'2024' not in stamp


@pcbnew
def test_fab_builds_one_deterministic_zip_that_verifies_and_a_wrong_size_fails(tmp_path, pcbnew_mod):
    b = build(tmp_path / 'afe.kicad_pcb')
    (tmp_path / 'bom.csv').write_text('a\n'); (tmp_path / 'cpl.csv').write_text('b\n')
    z1 = fab.build(b, str(tmp_path / 'o1'), str(tmp_path / 'bom.csv'), str(tmp_path / 'cpl.csv'), 'T-REVA', 'afe')
    z2 = fab.build(b, str(tmp_path / 'o2'), str(tmp_path / 'bom.csv'), str(tmp_path / 'cpl.csv'), 'T-REVA', 'afe')
    assert open(z1, 'rb').read() == open(z2, 'rb').read()                                           # byte for byte, whatever the plot time
    assert fab.manifest(z1)['zip_sha256'] == fab.manifest(z2)['zip_sha256']
    assert fab.verify(z1, b, 40.0, 30.0, 'T-REVA') == []                                            # the board's outline is 40 x 30
    assert fab.verify(z1, b, 40.0, 31.0, 'T-REVA')
    assert fab.verify(z1, b, 40.0, 30.0, 'OTHER-REVA')                                              # wrong ident: members missing
    assert sorted(zipfile.ZipFile(z1).namelist()) == fab.expected_members('T-REVA')


# ------------------------------------------------------------------------------------------------ render
@pcbnew
def test_render_refuses_a_missing_model_and_accepts_one_that_is_there(tmp_path, pcbnew_mod):
    miss = build(tmp_path / 'm.kicad_pcb', model='${KIPRJMOD}/lib/body.step')
    n, missing, unres = render.check_models(miss)
    assert missing == [('R1', '${KIPRJMOD}/lib/body.step')] and n >= 1            # the library footprint carries its own model too: that one resolves or is reported, not missing
    with pytest.raises(SystemExit):
        render.render(miss, str(tmp_path / 'x.png'))
    assert not (tmp_path / 'x.png').exists()
    (tmp_path / 'lib').mkdir(); (tmp_path / 'lib' / 'body.step').write_text('x')
    assert render.check_models(miss)[1] == []
    assert render.check_models(build(tmp_path / 'v.kicad_pcb', model='${NOPE_UNSET}/x.step'))[2]     # an unresolved variable is reported, not failed
    render.render(miss, str(tmp_path / 'ok.png'), width=300, height=200)
    assert (tmp_path / 'ok.png').stat().st_size > 1000


# ------------------------------------------------------------------------------------------------ ibom
def _fake_home(tmp_path, code=0):
    pkg = tmp_path / 'home' / 'InteractiveHtmlBom'
    pkg.mkdir(parents=True)
    (pkg / '__init__.py').write_text('')
    (pkg / 'generate_interactive_bom.py').write_text(textwrap.dedent(f'''
        import sys
        print("Debug: Adding duplicate image handler for 'PNG file'", file=sys.stderr)
        print("real warning", file=sys.stderr)
        print("INFO Created file " + sys.argv[1] + ".html", file=sys.stderr)
        sys.exit({code})
    '''))
    return str(tmp_path / 'home')


def test_ibom_runs_the_plugin_headless_keeps_real_messages_and_reports_a_missing_plugin(tmp_path):
    rc, created, err = ibom.run('b.kicad_pcb', home=str(tmp_path / 'nope'))
    assert rc == 3 and created is None and 'InteractiveHtmlBom' in err                              # never a silent skip
    rc, created, err = ibom.run('b.kicad_pcb', home=_fake_home(tmp_path))
    assert rc == 0 and created == 'b.kicad_pcb.html' and 'real warning' in err and 'duplicate image handler' not in err
    (tmp_path / 'again').mkdir()
    rc, created, _ = ibom.run('b.kicad_pcb', home=_fake_home(tmp_path / 'again', code=4))
    assert rc == 4                                                                                  # the plugin's own status


# ------------------------------------------------------------------------------------------------ pinlabels
def _table(tmp_path):
    p = tmp_path / 'table.md'
    p.write_text('| H1 pin | Arduino |\n|---|---|\n| 1 | A0 |\n| 2 | A1 (analog) |\n')
    return str(p)


def _setup(tmp_path, texts):
    # one socket J1 with pads 1 and 2 at x 10 and 12.54, y 5; a south band y -3..0 and a north band y 20..23; texts = [(text, x, y, h)]
    b = types.SimpleNamespace(
        fp_ref=np.array(['J1']), p_fp=np.array([0, 0]), p_pin=np.array(['1', '2']), p_x=np.array([10.0, 12.54]), p_y=np.array([5.0, 5.0]),
        p_bx0=np.array([9.5, 12.04]), p_bx1=np.array([10.5, 13.04]), p_by0=np.array([4.5, 4.5]), p_by1=np.array([5.5, 5.5]),
        t_text=[t[0] for t in texts], t_x=np.array([t[1] for t in texts]), t_y=np.array([t[2] for t in texts]), t_h=np.array([t[3] for t in texts]),
        r_fp=np.array([], int), r_x=np.array([]), r_y=np.array([]), r_h=np.array([]), r_ang=np.array([]), r_on_silk=np.array([], bool), r_layer=np.array([], int), path='')
    cfg = types.SimpleNamespace(
        FRAME=(100.0, 200.0), EDGE_SOCKETS={'J1': 'H1'}, PIN_TABLE=_table(tmp_path), KEEPOUTS=[('south', (0, -3, 30, 0)), ('north', (0, 20, 30, 23))],
        BASE_RECT=(0, 0, 30, 20), BOARD_RECT=(0, -3, 30, 23), PIN_LABEL_H=1.0, PIN_LABEL_W=1.0, PIN_LABEL_THICK=0.15, PIN_LABEL_EDGE_MARGIN=0.5,
        PIN_LABEL_PAD_GAP=0.3, PIN_LABEL_POS_TOL=0.05, PIN_LABEL_INK={'A0': 1.4, 'A1': 1.4}, PIN_LABEL_INK_H=1.2, PIN_LABEL_ALIASES={}, PIN_LABEL_FUNCTION_HEADERS=(),
        DESIGNATOR_GAP_ONE_LABEL=0.6, DESIGNATOR_ADVANCE=0.95, DESIGNATOR_INK_H=1.2)
    return b, cfg


def test_pinlabels_plan_apply_and_findings_in_the_configured_frame(tmp_path):
    b, cfg = _setup(tmp_path, [])
    plan = pinlabels.plan_labels(b, cfg)
    assert [(p.text, p.pin, p.angle) for p in plan] == [('A0', '1', 90.0), ('A1', '2', 90.0)]       # the table's cell without its parenthesis
    assert all(p.band == 'south' for p in plan) and abs(plan[0].y - (-3 + 0.5 + 0.7)) < 1e-9        # starts at the band's outer edge, runs inward by its ink
    board = '(kicad_pcb\n\t(gr_line\n\t)\n)\n'
    new = pinlabels.apply_labels(board, plan, cfg)
    assert new.count('(gr_text "A0"') == 1 and '(at 110 ' in new                                    # x 10 + FRAME 100
    assert pinlabels.apply_labels(new, plan, cfg) == new                                            # again: nothing changes
    assert pinlabels.apply_labels(board, plan, types.SimpleNamespace(**{**vars(cfg), 'FRAME': (0.0, 0.0)})) != new     # the frame is the configuration's
    good = [(p.text, p.x, p.y, 1.0) for p in plan]
    b2, _ = _setup(tmp_path, good)
    assert pinlabels.findings(b2, cfg) == []
    b3, _ = _setup(tmp_path, good[:1])                                                              # a label missing
    assert any('A1' in f for f in pinlabels.findings(b3, cfg))
    b4, _ = _setup(tmp_path, [(good[0][0], good[0][1], good[0][2], 1.0), (good[1][0], good[1][1], good[1][2], 1.2)])      # one label the wrong height
    assert any('1.20 mm high' in f for f in pinlabels.findings(b4, cfg))
    b5, _ = _setup(tmp_path, good + [('STRAY', 5.0, -2.0, 1.0)])                                    # silk text in a band that is not a pin label
    assert any('STRAY' in f for f in pinlabels.findings(b5, cfg))
    b6, _ = _setup(tmp_path, [(good[0][0], good[0][1], good[0][2], 1.0), (good[1][0], good[1][1] - 0.5, good[1][2], 1.0)])  # moved off its place
    assert pinlabels.findings(b6, cfg)


def test_pinlabels_a_header_missing_from_the_table_is_an_error(tmp_path):
    b, cfg = _setup(tmp_path, [])
    cfg.EDGE_SOCKETS = {'J1': 'H9'}
    with pytest.raises(ValueError):
        pinlabels.plan_labels(b, cfg)


def test_pinlabels_project_names_raise_when_missing_and_the_effective_configuration_says_where_each_value_came_from(tmp_path):
    b, cfg = _setup(tmp_path, [])
    del cfg.FRAME
    with pytest.raises(ValueError, match='FRAME'):
        pinlabels.plan_labels(b, cfg)                                                               # a frame is never defaulted
    b, cfg = _setup(tmp_path, [])
    del cfg.PIN_LABEL_THICK, cfg.PIN_LABEL_EDGE_MARGIN
    cfg.PIN_LABEL_H = 1.2                                                                           # the project's value
    cfg.PIN_LABEL_EDGE_MARGIN = 0.7
    txt = pinlabels.effective_config(cfg)
    line = {l.split()[0]: l.split()[1] for l in txt.splitlines()}
    assert line['PIN_LABEL_H'] == 'project' and line['PIN_LABEL_EDGE_MARGIN'] == 'project' and line['PIN_LABEL_THICK'] == 'default' and line['FRAME'] == 'project'
    assert pinlabels.PinCfg(cfg).PIN_LABEL_THICK == pinlabels.TUNABLES['PIN_LABEL_THICK']           # a tunable runs with its default
