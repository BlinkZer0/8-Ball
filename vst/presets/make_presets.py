#!/usr/bin/env python3
"""
Generates vst/presets/factory_presets.json (the factory presets) from the recipes below.
Do not edit the JSON by hand: edit a recipe here and run

    python make_presets.py                      writes factory_presets.json (keeps the stored level trims)
    python make_presets.py --match loud.json    reads EightBallTests --loudness output and sets every
                                                preset's presetGain so its loudest 100 ms sits at TARGET_DB
                                                (peaks are kept below PEAK_LIMIT), then writes the JSON

Level matching loop (from vst/; about 1000 presets, 3-4 minutes per pass):
    python presets\\make_presets.py
    ..\\EightBallTests.exe --presets presets\\factory_presets.json --loudness > %TEMP%\\loud.json
    python presets\\make_presets.py --match %TEMP%\\loud.json
    (and once more to confirm every preset is within +-0.5 dB; the trims are stored in trims.json)

Semantics (see docs/PLAN.md and vst/README.md): operator levels 0..1, ratio in 0.5 steps (the host snaps),
fine in cents, PM depth d = d^2 x 2 turns at modulator level 1, envelope points [time s, level, tension]
(absolute times; sync = beats), pitch / mod envelopes 0.5 = neutral, filter env amount = x5 octaves.
"""
import json, os, sys, math

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'factory_presets.json')
TRIMS = os.path.join(HERE, 'trims.json')
TARGET_DB = -18.0      # loudest 100 ms RMS at master 1, velocity 100
PEAK_LIMIT = 0.89      # about -1 dBFS before the master; above this the trim is held back

WAVE = {'sine': 0, 'saw': 1, 'square': 2, 'tri': 3, 'half': 4, 'noise': 5, 'custom': 6}
FLT = {'LP': 0, 'BP': 1, 'HP': 2}
ROUTE = {'par': 0, 'ser': 1, '12to3': 2}
LFOW = {'sine': 0, 'tri': 1, 'saw': 2, 'square': 3, 'sh': 4, 'drawn': 5}
DIVS = ['1/1', '1/2D', '1/2', '1/2T', '1/4D', '1/4', '1/4T', '1/8D', '1/8', '1/8T', '1/16D', '1/16', '1/16T', '1/32', '1/32T']
DST = {'soft': 0, 'hard': 1, 'fold': 2, 'crush': 3}
FXU = {'dst': 0, 'cho': 1, 'pha': 2, 'dly': 3, 'rev': 4, 'eq': 5, 'cmp': 6}
SRC = {'none': 0, 'lfo1': 1, 'lfo2': 2, 'lfo3': 3, 'lfo4': 4, 'vel': 35, 'wheel': 36, 'at': 37, 'bend': 38, 'key': 39}
for i in range(8):
    SRC['amp%d' % (i + 1)] = 5 + i
    SRC['pitch%d' % (i + 1)] = 13 + i
    SRC['mod%d' % (i + 1)] = 21 + i
for i in range(3):
    SRC['fcut%d' % (i + 1)] = 29 + i
    SRC['flvl%d' % (i + 1)] = 32 + i

# ---------------------------------------------------------------- envelopes ---
def env(points, sustain=None, loop=None, sync=False):
    e = {'points': [list(p) for p in points]}
    if sustain is not None: e['sustain'] = sustain
    if loop: e['loopStart'], e['loopEnd'] = loop
    if sync: e['sync'] = True
    return e

def adsr(a, d, s, r, peak=1.0, t=-0.5, sync=False):
    return env([[0, 0], [a, peak], [a + d, s, t], [a + d + r, 0, -0.5]], sustain=2, sync=sync)

def perc(a, d, t=-0.6, peak=1.0):
    """one-shot: attack, then decay to 0 (ignores note off)"""
    return env([[0, 0], [a, peak], [a + d, 0, t]], sustain=-1)

def flat(level=0.5):
    return env([[0, level], [1, level]], sustain=1)

def pitch_drop(start, time, t=-0.7):
    """pitch envelope from `start` (0.5 = none, 1 = +amount) down to neutral in `time` seconds"""
    return env([[0, start], [time, 0.5, t], [time + 1, 0.5]], sustain=2)

def swell(time, lo=0.5, hi=1.0, t=0.3):
    return env([[0, lo], [time, hi, t], [time + 1, hi]], sustain=2)

# ------------------------------------------------------------------ builder ---
class Preset:
    def __init__(self, cat, name):
        self.cat, self.name = cat, name
        self.p, self.envs, self.waves, self.lfoShapes, self.moddst = {}, {}, {}, {}, {}
        self.slot = 0

    # --- operators
    def op(self, k, ratio=None, level=None, wave=None, fine=None, vel=None, pan=None, unison=None, detune=None,
           spread=None, fixed=None, hz=None, keytrack=None, reset=None, pitchamt=None, modamt=None,
           amp=None, pitch=None, mod=None, partials=None, phases=None, shape=None):
        o = 'op%d' % k
        for key, v in (('Ratio', ratio), ('Level', level), ('Fine', fine), ('Vel', vel), ('Pan', pan), ('Unison', unison),
                       ('Detune', detune), ('Spread', spread), ('Hz', hz), ('KeyTrack', keytrack), ('PitchEnvAmt', pitchamt),
                       ('ModEnvAmt', modamt)):
            if v is not None: self.p[o + key] = v
        if wave is not None: self.p[o + 'Wave'] = WAVE[wave]
        if fixed is not None: self.p[o + 'Fixed'] = 1 if fixed else 0
        if reset is not None: self.p[o + 'PhaseReset'] = 1 if reset else 0
        if amp is not None: self.envs[o + 'Amp'] = amp
        if pitch is not None: self.envs[o + 'Pitch'] = pitch
        if mod is not None: self.envs[o + 'Mod'] = mod
        if partials is not None:
            self.waves[str(k)] = {'mode': 'harmonic', 'levels': list(partials), 'phases': list(phases or [0] * len(partials))}
            self.p[o + 'Wave'] = WAVE['custom']
        if shape is not None:
            self.waves[str(k)] = {'mode': 'drawn', 'shape': list(shape)}
            self.p[o + 'Wave'] = WAVE['custom']
        return self

    def pm(self, s, d, depth): self.p['pm%d%d' % (s, d)] = depth; return self
    def rm(self, s, d, depth): self.p['rm%d%d' % (s, d)] = depth; return self
    def fb(self, k, depth): return self.pm(k, k, depth)

    def out(self, k, dry=None, f1=None, f2=None, f3=None):
        for bus, v in (('Dry', dry), ('F1', f1), ('F2', f2), ('F3', f3)):
            if v is not None: self.p['out%d%s' % (k, bus)] = v
        return self

    def carriers(self, *ks, level=1.0, to='Dry'):
        """route these operators to one bus; op 1's default Dry send is cleared first"""
        self.p['out1Dry'] = 0
        for k in ks: self.p['out%d%s' % (k, to)] = level
        return self

    # --- filters
    def flt(self, f, type=None, cutoff=None, reso=None, slope=None, drive=None, key=None, env=None, vel=None, mix=None,
            on=None, cut=None, lvl=None):
        o = 'flt%d' % f
        if type is not None: self.p[o + 'Type'] = FLT[type]
        if slope is not None: self.p[o + 'Slope'] = 1 if slope == 24 else 0
        if on is not None: self.p[o + 'On'] = 1 if on else 0
        for key_, v in (('Cutoff', cutoff), ('Reso', reso), ('Drive', drive), ('KeyTrack', key), ('EnvAmt', env), ('Vel', vel), ('Mix', mix)):
            if v is not None: self.p[o + key_] = v
        if cut is not None: self.envs[o + 'Cutoff'] = cut
        if lvl is not None: self.envs[o + 'Level'] = lvl
        return self

    def routing(self, r): self.p['fltRouting'] = ROUTE[r]; return self

    # --- modulation
    def lfo(self, l, wave='sine', rate=None, div=None, depth=1.0, delay=None, phase=None, shape=None):
        o = 'lfo%d' % l
        self.p[o + 'On'] = 1
        self.p[o + 'Wave'] = LFOW[wave]
        if div is not None:
            self.p[o + 'Sync'] = 1
            self.p[o + 'Div'] = DIVS.index(div)
        if rate is not None: self.p[o + 'Rate'] = rate
        self.p[o + 'Depth'] = depth
        if delay is not None: self.p[o + 'Delay'] = delay
        if phase is not None: self.p[o + 'Phase'] = phase
        if shape is not None: self.lfoShapes[str(l)] = list(shape)
        return self

    def mod(self, src, dst, amt):
        self.slot += 1
        assert self.slot <= 16, self.name
        s = 'mod%d' % self.slot
        self.p[s + 'Src'] = SRC[src]
        self.p[s + 'Amt'] = amt
        self.moddst[s + 'Dst'] = dst
        return self

    # --- FX
    def dist(self, type='soft', drive=0.3, tone=1.0, mix=1.0, out=0.0):
        self.p.update({'dstOn': 1, 'dstType': DST[type], 'dstDrive': drive, 'dstTone': tone, 'dstMix': mix, 'dstOut': out}); return self
    def chorus(self, rate=0.8, depth=0.5, delay=7, feedback=0.0, spread=1.0, mix=0.5):
        self.p.update({'choOn': 1, 'choRate': rate, 'choDepth': depth, 'choDelay': delay, 'choFeedback': feedback, 'choSpread': spread, 'choMix': mix}); return self
    def phaser(self, rate=0.5, depth=0.7, stages=1, feedback=0.3, center=0.5, mix=0.5):
        self.p.update({'phaOn': 1, 'phaRate': rate, 'phaDepth': depth, 'phaStages': stages, 'phaFeedback': feedback, 'phaCenter': center, 'phaMix': mix}); return self
    def delay(self, time=None, div=None, feedback=0.4, pingpong=False, tone=0.6, mix=0.3):
        self.p.update({'dlyOn': 1, 'dlyFeedback': feedback, 'dlyPingPong': 1 if pingpong else 0, 'dlyTone': tone, 'dlyMix': mix})
        if div is not None: self.p.update({'dlySync': 1, 'dlyDiv': DIVS.index(div)})
        if time is not None: self.p['dlyTime'] = time
        return self
    def reverb(self, size=0.6, decay=0.5, damp=0.5, pre=10, width=1.0, mix=0.25):
        self.p.update({'revOn': 1, 'revSize': size, 'revDecay': decay, 'revDamp': damp, 'revPreDelay': pre, 'revWidth': width, 'revMix': mix}); return self
    def eq(self, lowcut=None, highcut=None, low=None, lowf=None, mid=None, midf=None, q=None, high=None, highf=None):
        self.p['eqOn'] = 1
        for key, v in (('LowCut', lowcut), ('HighCut', highcut), ('LowGain', low), ('LowFreq', lowf), ('MidGain', mid), ('MidFreq', midf),
                       ('MidQ', q), ('HighGain', high), ('HighFreq', highf)):
            if v is not None: self.p['eq' + key] = v
        return self
    def comp(self, thresh=-12, ratio=4, attack=10, release=100, makeup=0, limit=False, mix=1.0):
        self.p.update({'cmpOn': 1, 'cmpThresh': thresh, 'cmpRatio': ratio, 'cmpAttack': attack, 'cmpRelease': release, 'cmpMakeup': makeup, 'cmpLimit': 1 if limit else 0, 'cmpMix': mix}); return self
    def order(self, *units):
        for i, u in enumerate(units): self.p['fxOrder%d' % (i + 1)] = FXU[u]
        return self

    # --- global
    def mono(self, porta=None):
        self.p['voiceMode'] = 1
        if porta is not None: self.p.update({'portaOn': 1, 'portaTime': porta})
        return self
    def legato(self, porta=0.06):
        self.p.update({'voiceMode': 2, 'portaOn': 1, 'portaTime': porta}); return self
    def poly(self, n): self.p['poly'] = n; return self
    def os(self): self.p['oversample'] = 1; return self
    def bend(self, st): self.p['bendRange'] = st; return self

    def to_json(self):
        d = {'name': self.name, 'params': self.p}
        if self.moddst: d['modDst'] = self.moddst
        if self.waves: d['waves'] = self.waves
        if self.envs: d['envs'] = self.envs
        if self.lfoShapes: d['lfoShapes'] = self.lfoShapes
        return d


PRESETS = []
def P(cat, name):
    p = Preset(cat, name)
    PRESETS.append(p)
    return p

# =============================================================== recipes =====
# Every family below is an 8-operator architecture (stacks, shared modulators, cross-modulation,
# feedback, ring cells, carriers split across the three filters and Dry), so the presets show the
# 8 x 8 matrix off. Variants (Wide, Dirty, Echo, Slow, Bright, Dark, Short, Long, Hall, octave
# shifts) are deep copies with a modifier applied; the grids (divisions x LFO shapes x filters)
# build the dubstep library.
import copy

INIT = 'Init'; KEYS = 'Pianos & Keys'; ORCH = 'Orchestral & Acoustic'; DUB = 'Dubstep Bass'; BASS = 'Bass'
LEAD = 'Leads'; PAD = 'Pads & Textures'; PLUCK = 'Plucks & Arps'; EKEYS = 'Synth Keys & Organs'
STAB = 'Chords & Stabs'; DRUM = 'Drums & Percussion'; FXC = 'FX & Risers'

P(INIT, 'Init')

# ---------------------------------------------------------------- helpers ----
def scale_env_times(e, f):
    for pt in e['points']: pt[0] = round(pt[0] * f, 4)

def amp_envs(p):
    return [k for k in p.envs if k.endswith('Amp')]

def variant(base, suffix, fn, cat=None):
    q = copy.deepcopy(base)
    q.name = base.name + ' ' + suffix
    if cat: q.cat = cat
    fn(q)
    PRESETS.append(q)
    return q

def mod_wide(p):
    u = max(int(p.p.get('op1Unison', 1)), 4)
    p.op(1, unison=u, detune=max(p.p.get('op1Detune', 10), 14), spread=1.0)
    if 'op3Unison' in p.p or p.p.get('out3Dry', 0) or p.p.get('out3F1', 0): p.op(3, unison=max(int(p.p.get('op3Unison', 1)), 2), detune=9, spread=0.9)
    if 'choOn' not in p.p: p.chorus(rate=0.35, depth=0.35, mix=0.35)
def mod_dirty(p):
    if 'dstOn' in p.p: p.p['dstDrive'] = min(1.0, p.p['dstDrive'] + 0.3)
    else: p.dist('soft', drive=0.45, tone=0.8, mix=0.65)
    p.p.setdefault('eqOn', 1); p.p['eqLowGain'] = p.p.get('eqLowGain', 0) + 1.5; p.p.setdefault('eqLowFreq', 90)
def mod_echo(p):
    p.delay(div='1/8D', feedback=0.4, pingpong=True, tone=0.5, mix=0.3)
def mod_slow(p):
    # attacks 2.5x longer (0.6 .. 1.6 s), releases 1.6x; the sound still reaches full level inside the loudness window
    for k in amp_envs(p):
        e = p.envs[k]
        if len(e['points']) < 2: continue
        a0 = e['points'][1][0]
        a1 = round(min(max(a0 * 2.5, 0.6), 1.6), 4)
        e['points'][1][0] = a1
        for pt in e['points'][2:]: pt[0] = round((pt[0] - a0) * 1.6 + a1, 4)
    p.p['flt1Cutoff'] = p.p.get('flt1Cutoff', 2000) * 0.8
def mod_bright(p):
    for f in (1, 2, 3): p.p['flt%dCutoff' % f] = min(20000, p.p.get('flt%dCutoff' % f, 2000) * 2.2)
    p.p.setdefault('eqOn', 1); p.p['eqHighGain'] = p.p.get('eqHighGain', 0) + 3; p.p.setdefault('eqHighFreq', 6000)
def mod_dark(p):
    for f in (1, 2, 3): p.p['flt%dCutoff' % f] = max(80, p.p.get('flt%dCutoff' % f, 2000) * 0.4)
    for k in ('pm21', 'pm43', 'pm65', 'pm87'):
        if k in p.p: p.p[k] = round(p.p[k] * 0.7, 3)
def mod_short(p):
    # half the envelope times, but the decay never gets shorter than 150 ms (a stab must still be audible)
    for k in amp_envs(p):
        e = p.envs[k]
        f = 0.5
        if len(e['points']) >= 3 and e['points'][2][0] * f < 0.15: f = min(1.0, 0.15 / max(e['points'][2][0], 1e-3))
        scale_env_times(e, f)
def mod_long(p):
    for k in amp_envs(p): scale_env_times(p.envs[k], 2.2)
def mod_hall(p):
    p.reverb(size=0.92, decay=0.82, damp=0.4, pre=30, mix=0.38)
def mod_oct_down(p):
    for k in range(1, 9):
        key = 'op%dRatio' % k
        if key in p.p and not p.p.get('op%dFixed' % k): p.p[key] = max(0.5, p.p[key] * 0.5)
def mod_oct_up(p):
    for k in range(1, 9):
        key = 'op%dRatio' % k
        if key in p.p and not p.p.get('op%dFixed' % k): p.p[key] = min(32, p.p[key] * 2)
def mod_trem(p):
    p.lfo(4, 'sine', rate=5.0, delay=0.2).mod('lfo4', 'op1Level', -0.3).mod('lfo4', 'op3Level', -0.3)
def mod_vib(p):
    p.lfo(4, 'sine', rate=5.6, delay=0.35).mod('lfo4', 'op1Fine', 0.1).mod('lfo4', 'op3Fine', 0.1)

def vibrato(p, rate=5.5, delay=0.35, cents=0.12, ops=(1, 3), lfo=2):
    p.lfo(lfo, 'sine', rate=rate, delay=delay)
    for k in ops: p.mod('lfo%d' % lfo, 'op%dFine' % k, cents)
    return p

# ================================================================= PIANOS ====
# 8 ops: three carriers (fundamental, a detuned twin, the octave) each with its own modulator, a
# hammer modulator shared by the first two carriers, and a soundboard sub carrier.
def piano(name, bright=0.42, hammer=0.25, detune=4, soft=False, honky=False, cat=KEYS):
    p = P(cat, name)
    a = adsr(0.002, 3.0, 0.0, 0.25, t=-0.6)
    p.op(1, ratio=1, level=0.9, vel=0.6, amp=a)
    p.op(2, ratio=1, level=0.6, vel=0.95, amp=perc(0.002, 1.2)).pm(2, 1, bright)
    p.op(3, ratio=1, fine=detune, level=0.55, vel=0.6, amp=adsr(0.002, 2.5, 0.0, 0.25, t=-0.6))
    p.op(4, ratio=3, level=0.5, vel=0.9, amp=perc(0.002, 0.9)).pm(4, 3, bright * 0.7)
    p.op(5, ratio=2, level=0.35, vel=0.8, amp=perc(0.002, 1.6))
    p.op(6, ratio=2, level=0.5, vel=0.9, amp=perc(0.002, 0.8)).pm(6, 5, bright * 0.5).pm(2, 5, bright * 0.25)
    p.op(7, ratio=0.5, level=0.3, vel=0.4, amp=adsr(0.004, 2.0, 0.0, 0.25, t=-0.6))
    p.op(8, ratio=7, level=0.4, vel=1.0, amp=perc(0.001, 0.09)).pm(8, 1, hammer).pm(8, 3, hammer * 0.6).pm(8, 7, hammer * 0.3)
    p.carriers(1, 3, level=0.8, to='F1').out(5, f2=0.7).out(7, dry=0.7)
    p.flt(1, 'LP', cutoff=5000 if not soft else 2600, key=0.5, vel=0.4).flt(2, 'LP', cutoff=7000, key=0.4)
    if honky: p.op(3, fine=22).op(1, fine=-10)
    p.eq(low=1.5, lowf=120, high=1.5, highf=6000).reverb(size=0.5, decay=0.4, mix=0.12)
    return p
piano('Grand Piano')
piano('Bright Piano', bright=0.5, hammer=0.32)
piano('Soft Piano', bright=0.32, hammer=0.18, soft=True)
piano('Honky Tonk', bright=0.46, honky=True).chorus(rate=0.3, depth=0.2, mix=0.25)
piano('Upright Piano', bright=0.38, hammer=0.28, detune=6).eq(mid=2, midf=800, q=1.2)
for nm in ('Grand Piano', 'Bright Piano', 'Soft Piano', 'Upright Piano'):
    variant(next(x for x in PRESETS if x.name == nm), 'Hall', mod_hall)

# harpsichord: plectrum stack (2>1, 3>2), a second string (4, fine) with 5, 6 feedback buzz, 7 octave, 8 release click
p = P(KEYS, 'Harpsichord')
p.op(1, ratio=1, level=0.9, vel=0.3, amp=perc(0.001, 1.4)).op(2, ratio=1, level=0.85, vel=0.4, amp=perc(0.001, 0.9)).pm(2, 1, 0.55).fb(2, 0.2)
p.op(3, ratio=3, level=0.4, amp=perc(0.001, 0.5)).pm(3, 2, 0.3).op(4, ratio=1, fine=5, level=0.7, amp=perc(0.001, 1.3)).op(5, ratio=2, level=0.7, amp=perc(0.001, 0.8)).pm(5, 4, 0.5)
p.op(6, ratio=4, level=0.4, amp=perc(0.001, 0.3)).fb(6, 0.4).pm(6, 4, 0.2).op(7, ratio=2, level=0.5, amp=perc(0.001, 1.2)).op(8, ratio=9, level=0.3, amp=perc(0.001, 0.04)).pm(8, 1, 0.2).pm(8, 7, 0.2)
p.carriers(1, 4, 7, level=0.7, to='F1').flt(1, 'LP', cutoff=7000, key=0.4).eq(low=-2, lowf=150, high=3, highf=5000).reverb(size=0.4, decay=0.35, mix=0.14)
variant(p, 'Lute Stop', lambda q: q.flt(1, cutoff=2200).op(7, level=0.2))

p = P(KEYS, 'Clavinet')
p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.001, 1.5, 0.0, 0.08, t=-0.6)).op(2, ratio=1, level=0.8, vel=0.9, amp=perc(0.001, 0.35)).pm(2, 1, 0.58)
p.op(3, ratio=5, level=0.35, vel=1, amp=perc(0.001, 0.05)).pm(3, 1, 0.22).op(4, ratio=2, level=0.7, vel=0.6, amp=adsr(0.001, 1.2, 0.0, 0.08, t=-0.6)).op(5, ratio=3, level=0.6, vel=0.9, amp=perc(0.001, 0.25)).pm(5, 4, 0.4)
p.op(6, ratio=1, level=0.5, amp=perc(0.001, 0.3)).fb(6, 0.5).pm(6, 2, 0.25).op(7, ratio=0.5, level=0.4, amp=adsr(0.001, 1.0, 0.0, 0.08)).op(8, wave='noise', level=0.25, amp=perc(0.001, 0.012))
p.carriers(1, 4, to='F1').out(7, dry=0.5).out(8, f2=0.8).flt(1, 'LP', cutoff=1800, reso=0.35, env=0.45, vel=0.3, key=0.4, cut=perc(0.001, 0.25)).flt(2, 'HP', cutoff=2500)
p.eq(mid=3, midf=1800, q=1.2).comp(thresh=-18, ratio=3, attack=5)
variant(p, 'Phased', lambda q: q.phaser(rate=0.35, depth=0.7, stages=1, feedback=0.4, mix=0.45))
variant(p, 'Wah', lambda q: q.flt(1, reso=0.65).mod('wheel', 'flt1Cutoff', 0.5))

# e-piano: tine pair (2>1), body pair (4>3), bark (5>3 with velocity), bell (6>1 high ratio), sub (7), key-off noise (8)
def epiano(name, tine=0.3, body=0.45, bark=0.2, drive=0.0, trem=0.0, cat=KEYS):
    p = P(cat, name)
    p.op(1, ratio=1, level=1, vel=0.55, amp=adsr(0.002, 3.5, 0.0, 0.3, t=-0.6))
    p.op(2, ratio=14, level=0.35, vel=0.95, amp=perc(0.002, 0.3)).pm(2, 1, tine)
    p.op(3, ratio=1, level=0.8, vel=0.5, amp=adsr(0.002, 3.0, 0.0, 0.3, t=-0.6))
    p.op(4, ratio=1, level=0.6, vel=0.85, amp=perc(0.002, 1.6)).pm(4, 3, body)
    p.op(5, ratio=2, level=0.5, vel=1.0, amp=perc(0.002, 0.4)).pm(5, 3, bark).pm(5, 1, bark * 0.5)
    p.op(6, ratio=7, level=0.3, vel=0.9, amp=perc(0.002, 0.5)).pm(6, 1, 0.12)
    p.op(7, ratio=0.5, level=0.35, vel=0.4, amp=adsr(0.004, 2.5, 0.0, 0.3))
    p.op(8, wave='noise', level=0.1, amp=perc(0.001, 0.02))
    p.carriers(1, 3, level=0.7).out(7, dry=0.6).out(8, f2=0.7).flt(2, 'BP', cutoff=3000, reso=0.4)
    if trem: p.lfo(1, 'sine', rate=5.2).mod('lfo1', 'op1Pan', trem).mod('lfo1', 'op3Pan', -trem)
    if drive: p.dist('soft', drive=drive, tone=0.7, mix=0.6)
    p.chorus(rate=0.5, depth=0.25, mix=0.25).reverb(size=0.5, decay=0.4, mix=0.15)
    return p
epiano('Rhodes Tine', trem=0.5)
epiano('Rhodes Dark', tine=0.18, body=0.35, bark=0.1).eq(high=-3, highf=4000)
epiano('Wurli', tine=0.2, body=0.55, bark=0.3, drive=0.25, trem=0.35).eq(mid=2, midf=1200)
epiano('DX Piano', tine=0.4, body=0.5, bark=0.25).op(5, ratio=1, fine=6)
epiano('Suitcase', tine=0.28, body=0.48, trem=0.6).phaser(rate=0.2, depth=0.4, stages=1, mix=0.25)
epiano('Dyno Bell', tine=0.45, body=0.4, bark=0.15).op(6, level=0.5).eq(high=3, highf=5000)
for nm in ('Rhodes Tine', 'Wurli', 'DX Piano'):
    variant(next(x for x in PRESETS if x.name == nm), 'Hall', mod_hall)
    variant(next(x for x in PRESETS if x.name == nm), 'Echo', mod_echo)

p = P(KEYS, 'Toy Piano')
p.op(1, ratio=1, level=0.8, amp=perc(0.001, 1.2)).op(2, ratio=4, fine=20, level=0.5, amp=perc(0.001, 0.4)).pm(2, 1, 0.3)
p.op(3, ratio=10, fine=-30, level=0.3, amp=perc(0.001, 0.2)).pm(3, 1, 0.15).op(4, ratio=3, level=0.4, amp=perc(0.001, 0.9)).op(5, ratio=11, level=0.3, amp=perc(0.001, 0.15)).pm(5, 4, 0.25)
p.op(6, ratio=2, fine=14, level=0.35, amp=perc(0.001, 0.7)).op(7, ratio=5.5, level=0.3, amp=perc(0.001, 0.3)).pm(7, 6, 0.3).op(8, wave='noise', level=0.2, amp=perc(0.001, 0.015))
p.carriers(1, 4, 6, level=0.7).out(8, dry=0.5).eq(low=-4, lowf=200).reverb(size=0.3, decay=0.3, mix=0.15)

p = P(KEYS, 'Music Box')
p.op(1, ratio=1, level=0.8, amp=perc(0.001, 2.0)).op(2, ratio=4, level=0.5, amp=perc(0.001, 0.5)).pm(2, 1, 0.33)
p.op(3, ratio=8, level=0.25, amp=perc(0.001, 0.2)).pm(3, 1, 0.12).op(4, ratio=2, level=0.5, amp=perc(0.001, 1.6)).op(5, ratio=6, level=0.4, amp=perc(0.001, 0.4)).pm(5, 4, 0.3)
p.op(6, ratio=3, level=0.35, amp=perc(0.001, 1.2)).op(7, ratio=12, level=0.3, amp=perc(0.001, 0.2)).pm(7, 6, 0.2).op(8, ratio=1, fine=8, level=0.4, amp=perc(0.001, 1.8))
p.carriers(1, 4, 6, 8, level=0.6).eq(low=-6, lowf=300).reverb(size=0.6, decay=0.5, mix=0.25)
variant(p, 'Celesta', lambda q: (q.op(4, level=0.3).op(2, ratio=3), mod_hall(q)))

p = P(KEYS, 'Glass Celesta')
p.op(1, ratio=1, level=0.9, amp=perc(0.002, 1.8)).op(2, ratio=5, level=0.4, amp=perc(0.002, 0.6)).pm(2, 1, 0.28)
p.op(3, ratio=2, level=0.6, amp=perc(0.002, 1.4)).op(4, ratio=9, level=0.3, amp=perc(0.002, 0.3)).pm(4, 3, 0.2).op(5, ratio=4, level=0.4, amp=perc(0.002, 1.0)).op(6, ratio=13, level=0.25, amp=perc(0.002, 0.2)).pm(6, 5, 0.18)
p.op(7, ratio=1, fine=4, level=0.5, amp=perc(0.002, 1.6)).op(8, ratio=3, level=0.3, amp=perc(0.002, 0.5)).pm(8, 7, 0.2).rm(8, 5, 0.3)
p.carriers(1, 3, 5, 7, level=0.6, to='F1').flt(1, 'HP', cutoff=300).delay(div='1/8D', feedback=0.3, pingpong=True, tone=0.7, mix=0.2).reverb(size=0.7, decay=0.6, mix=0.3)

# ============================================================= ORCHESTRAL ====
# strings: two carriers a few cents apart (1, 3) with their own modulators (2, 4), a shared
# brightness modulator (5) into both, a bow-noise op (7) through filter 2, a sub-octave carrier (8)
def strings(name, cat=ORCH, attack=0.35, release=0.6, cutoff=3500, unison=4, detune=12, lo=False, pizz=False, trem=False, ens=False):
    p = P(cat, name)
    a = perc(0.003, 0.5) if pizz else adsr(attack, 0.3, 0.9, release, t=0.2)
    p.op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.8, vel=0.4, amp=a)
    p.op(2, ratio=1, level=0.7, vel=0.5, amp=a).pm(2, 1, 0.42).fb(2, 0.25)
    p.op(3, ratio=1, fine=7, level=0.8, unison=max(1, unison - 2), detune=detune, spread=0.8, vel=0.4, amp=a)
    p.op(4, ratio=2, level=0.5, vel=0.5, amp=a).pm(4, 3, 0.3)
    p.op(5, ratio=3 if not lo else 2, level=0.35, amp=a).pm(5, 1, 0.18).pm(5, 3, 0.15)
    p.op(6, ratio=1, level=0.4, amp=a).fb(6, 0.3).pm(6, 2, 0.2)
    p.op(7, wave='noise', level=0.12 if not pizz else 0.25, amp=adsr(0.05, 0.2, 0.5, 0.2) if not pizz else perc(0.001, 0.03))
    p.op(8, ratio=0.5, level=0.35 if lo or ens else 0.15, vel=0.3, amp=a)
    p.carriers(1, 3, to='F1').out(8, f1=0.8).out(7, f2=1)
    p.flt(1, 'LP', cutoff=cutoff, key=0.4, vel=0.3, reso=0.1, env=0.25 if pizz else 0.0, cut=perc(0.002, 0.3) if pizz else None)
    p.flt(2, 'BP', cutoff=3200, reso=0.4)
    if not pizz: vibrato(p, ops=(1, 3), cents=0.08)
    if trem: p.lfo(3, 'sine', rate=6.5).mod('lfo3', 'op1Level', -0.5).mod('lfo3', 'op3Level', -0.5)
    p.chorus(rate=0.4, depth=0.3, mix=0.3 if ens else 0.15).reverb(size=0.75, decay=0.65, mix=0.22)
    return p
for nm, kw in (('Violin', dict(unison=1, attack=0.12, cutoff=5000)), ('Viola', dict(unison=1, attack=0.14, cutoff=3800)),
               ('Cello', dict(unison=1, attack=0.15, cutoff=2600, lo=True)), ('Double Bass', dict(unison=1, attack=0.08, cutoff=1400, lo=True))):
    strings(nm, **kw)
    strings(nm + ' Staccato', **dict(kw, attack=0.02)).op(1, amp=adsr(0.02, 0.25, 0.0, 0.15)).op(3, amp=adsr(0.02, 0.25, 0.0, 0.15))
    strings(nm + ' Tremolo', **dict(kw, trem=True))
    strings(nm + ' Pizzicato', **dict(kw, pizz=True, cutoff=2500))
strings('String Section', ens=True)
strings('String Section Slow', ens=True, attack=0.9, release=1.2)
strings('String Section Tremolo', ens=True, trem=True)
strings('Chamber Strings', unison=2, detune=8, ens=True, cutoff=4200)
strings('Pizzicato Section', pizz=True, cutoff=2500, ens=True)

p = P(ORCH, 'Harp')
p.op(1, ratio=1, level=0.9, vel=0.5, amp=perc(0.002, 2.2)).op(2, ratio=2, level=0.5, vel=0.9, amp=perc(0.002, 0.9)).pm(2, 1, 0.3)
p.op(3, ratio=5, level=0.3, vel=1, amp=perc(0.001, 0.15)).pm(3, 1, 0.14).op(4, ratio=1, fine=6, level=0.6, amp=perc(0.002, 2.0)).op(5, ratio=3, level=0.4, amp=perc(0.002, 0.6)).pm(5, 4, 0.25)
p.op(6, ratio=2, level=0.4, amp=perc(0.002, 1.5)).op(7, ratio=7, level=0.25, amp=perc(0.001, 0.2)).pm(7, 6, 0.2).op(8, wave='noise', level=0.15, amp=perc(0.001, 0.01))
p.carriers(1, 4, 6, level=0.7).out(8, dry=0.4).reverb(size=0.7, decay=0.6, mix=0.28)
variant(p, 'Hall', mod_hall)
variant(p, 'Glissando', lambda q: q.delay(div='1/16', feedback=0.5, pingpong=True, tone=0.7, mix=0.3))

# winds: carrier (1) with a swell modulator (2), the odd-harmonic twin (3 <- 4), breath noise (5)
# through a band-pass, a formant carrier (6 <- 7) into filter 1, sub (8)
def wind(name, pm=0.12, ratio2=1, attack=0.08, breath=0.12, cutoff=5000, odd=False, formant=None, cat=ORCH, ens=False):
    p = P(cat, name)
    a = adsr(attack, 0.2, 0.9, 0.12, t=0.2)
    if odd: p.op(1, partials=[1, 0, 0.33, 0, 0.2, 0, 0.14, 0, 0.1], level=1, vel=0.4, amp=a)
    else:   p.op(1, ratio=1, level=1, vel=0.4, amp=a)
    if ens: p.op(1, unison=3, detune=9, spread=0.8)
    p.op(2, ratio=ratio2, level=0.6, vel=0.6, amp=a, mod=swell(0.15, 0.3, 0.6)).pm(2, 1, pm)
    p.op(3, ratio=1, fine=-5, level=0.5, vel=0.4, amp=a).op(4, ratio=3, level=0.4, amp=a).pm(4, 3, pm * 0.8).pm(4, 1, pm * 0.3)
    p.op(5, wave='noise', level=breath, vel=0.7, amp=perc(0.005, 0.12)).out(5, f2=1)
    p.op(6, ratio=2, level=0.35, amp=a).op(7, ratio=4, level=0.3, amp=a, mod=swell(0.3, 0.4, 0.7)).pm(7, 6, 0.25).fb(7, 0.2)
    p.op(8, ratio=0.5, level=0.2, amp=a)
    p.flt(2, 'BP', cutoff=2500, reso=0.5)
    p.carriers(1, 3, to='F1').out(6, f1=0.6).out(8, dry=0.5).flt(1, 'LP', cutoff=cutoff, key=0.5)
    if formant: p.flt(1, 'BP', cutoff=formant, reso=0.45, mix=0.6)
    vibrato(p, ops=(1, 3), cents=0.1, delay=0.45)
    p.reverb(size=0.55, decay=0.5, mix=0.2)
    return p
for nm, kw in (('Flute', dict(pm=0.1)), ('Piccolo', dict(pm=0.08, attack=0.05, breath=0.18, cutoff=9000)),
               ('Oboe', dict(pm=0.3, ratio2=2, attack=0.05, breath=0.04, formant=1200)), ('Clarinet', dict(pm=0.15, ratio2=3, attack=0.06, breath=0.03, odd=True, cutoff=3000)),
               ('Bassoon', dict(pm=0.35, ratio2=1, attack=0.07, breath=0.05, cutoff=1500, formant=550)), ('Pan Flute', dict(pm=0.06, attack=0.04, breath=0.3, cutoff=4000)),
               ('English Horn', dict(pm=0.28, ratio2=2, attack=0.06, breath=0.04, formant=900, cutoff=4000)), ('Recorder', dict(pm=0.05, attack=0.03, breath=0.2, cutoff=6000))):
    wind(nm, **kw)
    wind(nm + ' Ensemble', ens=True, **kw)

# brass: carrier (1) and its octave twin (3) with modulators swelling in (2, 4), a shared bright
# modulator (5) with feedback, a sub (6), lip-noise (7) and a growl ring cell (8 x 1) on the wheel
def brass(name, pm=0.5, attack=0.05, cutoff=3500, unison=1, detune=8, ratio3=2, cat=ORCH, lo=False, muted=False):
    p = P(cat, name)
    a = adsr(attack, 0.25, 0.85, 0.15, t=0.2)
    p.op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.7, vel=0.4, amp=a)
    p.op(2, ratio=1, level=0.8, vel=0.8, amp=a, mod=swell(0.12, 0.35, 0.6)).pm(2, 1, pm).fb(2, 0.15)
    p.op(3, ratio=ratio3, level=0.4, vel=0.7, amp=a).op(4, ratio=1, level=0.6, amp=a, mod=swell(0.15, 0.3, 0.6)).pm(4, 3, pm * 0.8)
    p.op(5, ratio=3, level=0.4, vel=0.8, amp=a).fb(5, 0.3).pm(5, 2, 0.25).pm(5, 4, 0.2)
    p.op(6, ratio=0.5, level=0.3, amp=a).op(7, wave='noise', level=0.08, amp=perc(0.005, 0.06)).op(8, ratio=1, fine=3, level=0.6, amp=a).rm(8, 1, 0.0)
    p.carriers(1, 3, to='F1').out(6, dry=0.5).out(7, f2=1).flt(2, 'BP', cutoff=2000, reso=0.4)
    p.flt(1, 'LP', cutoff=cutoff if not muted else cutoff * 0.35, key=0.5, vel=0.4, env=0.2, cut=adsr(0.08, 0.3, 0.6, 0.2), reso=0.3 if muted else 0.1)
    p.mod('wheel', 'rm81', 0.5)
    if lo: p.eq(low=2.5, lowf=120)
    vibrato(p, ops=(1, 3), cents=0.06, delay=0.5)
    p.reverb(size=0.6, decay=0.5, mix=0.18)
    return p
for nm, kw in (('Trumpet', dict(pm=0.55, cutoff=5000)), ('French Horn', dict(pm=0.32, attack=0.1, cutoff=1800, ratio3=1)),
               ('Trombone', dict(pm=0.45, attack=0.07, cutoff=2600)), ('Tuba', dict(pm=0.3, attack=0.08, cutoff=900, lo=True)),
               ('Flugelhorn', dict(pm=0.4, attack=0.06, cutoff=2800)), ('Euphonium', dict(pm=0.35, attack=0.08, cutoff=1600, lo=True))):
    brass(nm, **kw)
    brass(nm + ' Muted', muted=True, **kw)
    brass(nm + ' Section', unison=3, detune=10, **dict(kw, cutoff=kw['cutoff'] * 0.8)).chorus(rate=0.35, depth=0.3, mix=0.3)

def guitar(name, pm=0.35, pick=0.15, decay=2.0, cutoff=3500, lo=False, cat=ORCH):
    p = P(cat, name)
    p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.002, decay, 0.0, 0.15, t=-0.6))
    p.op(2, ratio=1, level=0.75, vel=0.9, amp=perc(0.002, decay * 0.35)).pm(2, 1, pm).fb(2, 0.12)
    p.op(3, ratio=3, level=0.4, vel=1, amp=perc(0.001, 0.12)).pm(3, 1, pick).pm(3, 4, pick * 0.5)
    p.op(4, ratio=2, level=0.5, vel=0.6, amp=adsr(0.002, decay * 0.8, 0.0, 0.15, t=-0.6)).op(5, ratio=2, level=0.5, vel=0.9, amp=perc(0.002, decay * 0.3)).pm(5, 4, pm * 0.7)
    p.op(6, ratio=1, fine=5, level=0.4, amp=adsr(0.002, decay, 0.0, 0.15, t=-0.6)).op(7, ratio=5, level=0.3, amp=perc(0.001, 0.08)).pm(7, 6, pick).op(8, wave='noise', level=0.15, amp=perc(0.001, 0.008))
    p.carriers(1, 4, 6, level=0.7, to='F1').out(8, dry=0.5).flt(1, 'LP', cutoff=cutoff, key=0.4, env=0.3, vel=0.3, cut=perc(0.002, 0.4))
    if lo: p.eq(low=3, lowf=90).comp(thresh=-16, ratio=3, attack=8)
    p.reverb(size=0.45, decay=0.4, mix=0.14)
    return p
guitar('Nylon Guitar'); guitar('Steel Guitar', pm=0.5, pick=0.2, cutoff=5000).eq(high=2, highf=5000)
guitar('Bass Guitar', pm=0.42, pick=0.1, decay=2.5, cutoff=1500, lo=True); guitar('12-String', pm=0.45, pick=0.18, cutoff=4500).op(6, fine=12, level=0.6).chorus(rate=0.3, depth=0.3, mix=0.3)
guitar('Banjo', pm=0.55, pick=0.3, decay=0.8, cutoff=6000).fb(2, 0.3)
mod_oct_up(guitar('Mandolin', pm=0.5, pick=0.25, decay=0.9, cutoff=7000).op(6, fine=10, level=0.6))
guitar('Ukulele', pm=0.3, pick=0.12, decay=1.2, cutoff=4000)
for nm in ('Nylon Guitar', 'Steel Guitar'):
    variant(next(x for x in PRESETS if x.name == nm), 'Hall', mod_hall)
    variant(next(x for x in PRESETS if x.name == nm), 'Muted', lambda q: (mod_short(q), q.flt(1, cutoff=1500)))

def mallet(name, ratio=4, pm=0.3, hit=0.12, decay=0.7, trem=0.0, bright_ratio=None, bright=0.12, cat=ORCH):
    p = P(cat, name)
    p.op(1, ratio=1, level=1, vel=0.5, amp=perc(0.001, decay))
    p.op(2, ratio=ratio, level=0.6, vel=0.9, amp=perc(0.001, hit)).pm(2, 1, pm)
    p.op(3, ratio=bright_ratio or ratio * 2, level=0.4, vel=0.8, amp=perc(0.001, decay * 0.4)).pm(3, 1, bright)
    p.op(4, ratio=1, fine=3, level=0.6, vel=0.5, amp=perc(0.001, decay * 1.2)).op(5, ratio=ratio, level=0.5, amp=perc(0.001, hit * 0.8)).pm(5, 4, pm * 0.8)
    p.op(6, ratio=2, level=0.4, amp=perc(0.001, decay * 0.6)).op(7, ratio=ratio + 1, level=0.3, amp=perc(0.001, hit)).pm(7, 6, pm * 0.6).op(8, wave='noise', level=0.2, amp=perc(0.001, 0.006))
    p.carriers(1, 4, 6, level=0.7).out(8, dry=0.6)
    if trem: p.lfo(1, 'sine', rate=4.5).mod('lfo1', 'op1Level', trem).mod('lfo1', 'op4Level', trem)
    p.reverb(size=0.5, decay=0.45, mix=0.2)
    return p
mallet('Marimba', ratio=4, pm=0.35, hit=0.1, decay=0.8).eq(low=2, lowf=150)
mallet('Marimba Soft', ratio=4, pm=0.2, hit=0.15, decay=0.9).flt(1, 'LP', cutoff=3000)
mallet('Xylophone', ratio=3, pm=0.4, hit=0.06, decay=0.4, bright_ratio=9).eq(low=-6, lowf=300)
mallet('Vibraphone', ratio=4, pm=0.22, hit=1.5, decay=3.0, trem=-0.3).chorus(rate=0.2, depth=0.2, mix=0.2)
mallet('Vibraphone Bowed', ratio=4, pm=0.15, hit=2.5, decay=4.0).op(1, amp=adsr(1.2, 0.5, 0.8, 1.5)).op(4, amp=adsr(1.2, 0.5, 0.8, 1.5))
mallet('Glockenspiel', ratio=7, pm=0.28, hit=0.35, decay=1.6, bright_ratio=10).eq(low=-6, lowf=400)
mallet('Tubular Bells', ratio=3.5, pm=0.5, hit=2.5, decay=5.0, bright_ratio=1.5, bright=0.3).reverb(size=0.85, decay=0.75, mix=0.3)
mallet('Crotales', ratio=6, pm=0.3, hit=0.8, decay=2.5, bright_ratio=11).eq(low=-8, lowf=500)
mallet('Kalimba', ratio=2, pm=0.25, hit=0.08, decay=1.0)
mallet('Steel Drum', ratio=2, pm=0.45, hit=0.2, decay=1.2, bright_ratio=5, bright=0.25).rm(3, 1, 0.2).eq(mid=3, midf=1200)
mallet('Balafon', ratio=3, pm=0.35, hit=0.08, decay=0.5, bright_ratio=7).eq(low=2, lowf=200)
mallet('Gamelan', ratio=2.5, pm=0.4, hit=0.6, decay=2.2, bright_ratio=4.5, bright=0.3).rm(5, 4, 0.3).reverb(size=0.8, decay=0.7, mix=0.3)

def organ8(name, drawbars, perc_=0.0, drive=0.0, leslie=0.0, cat=ORCH, click=0.0):
    p = P(cat, name)
    for k, (r, l) in enumerate(drawbars[:7], start=1):
        p.op(k, ratio=r, level=l, vel=0.15, amp=adsr(0.005, 0.05, 1, 0.05))
    p.carriers(*range(1, min(len(drawbars), 7) + 1), level=0.5)
    if perc_: p.op(8, ratio=3, level=perc_, amp=perc(0.001, 0.3)).out(8, dry=0.5)
    elif click: p.op(8, wave='noise', level=click, amp=perc(0.001, 0.01)).out(8, dry=0.5)
    if leslie: p.lfo(1, 'sine', rate=leslie).mod('lfo1', 'op1Pan', 0.5).mod('lfo1', 'op2Pan', -0.5).mod('lfo1', 'op3Pan', 0.4).mod('lfo1', 'op1Fine', 0.03)
    if drive: p.dist('soft', drive=drive, tone=0.7, mix=0.6)
    p.reverb(size=0.5, decay=0.4, mix=0.15)
    return p
organ8('Church Organ', [(1, 0.8), (2, 0.6), (3, 0.35), (4, 0.4), (6, 0.2), (8, 0.25), (0.5, 0.5)]).chorus(rate=0.25, depth=0.15, mix=0.2).reverb(size=0.95, decay=0.85, pre=30, mix=0.4)
organ8('Church Organ Full', [(1, 0.9), (2, 0.8), (3, 0.5), (4, 0.6), (5, 0.3), (6, 0.35), (8, 0.4)]).reverb(size=0.98, decay=0.9, pre=40, mix=0.45).eq(low=2, lowf=80)
organ8('Pipe Flute Stop', [(1, 0.9), (2, 0.3), (4, 0.15), (0.5, 0.4), (3, 0.1), (8, 0.08)]).reverb(size=0.9, decay=0.8, mix=0.4)
organ8('Harmonium', [(1, 0.8), (2, 0.5), (3, 0.4), (4, 0.3), (5, 0.2), (6, 0.15), (0.5, 0.3)]).op(1, unison=2, detune=10).chorus(rate=0.5, depth=0.2, mix=0.25)

p = P(ORCH, 'Accordion')
p.op(1, ratio=1, level=1, unison=2, detune=14, spread=0.6, vel=0.3, amp=adsr(0.03, 0.1, 1.0, 0.1))
p.op(2, ratio=1, level=0.7, amp=adsr(0.03, 0.1, 1.0, 0.1)).pm(2, 1, 0.48).fb(2, 0.2).op(3, ratio=2, level=0.4, amp=adsr(0.03, 0.1, 1.0, 0.1)).pm(3, 1, 0.2)
p.op(4, ratio=1, fine=-12, level=0.8, amp=adsr(0.03, 0.1, 1.0, 0.1)).op(5, ratio=1, level=0.6, amp=adsr(0.03, 0.1, 1.0, 0.1)).pm(5, 4, 0.45).op(6, ratio=2, level=0.5, amp=adsr(0.03, 0.1, 1.0, 0.1)).op(7, ratio=3, level=0.4, amp=adsr(0.03, 0.1, 1.0, 0.1)).pm(7, 6, 0.3)
p.op(8, ratio=0.5, level=0.4, amp=adsr(0.03, 0.1, 1.0, 0.1))
p.carriers(1, 4, 6, to='F1').out(8, dry=0.6).flt(1, 'LP', cutoff=4000, key=0.3).lfo(1, 'sine', rate=6).mod('lfo1', 'op1Level', -0.15).reverb(size=0.5, decay=0.4, mix=0.15)
variant(p, 'Musette', lambda q: q.op(4, fine=-22).op(1, detune=22))
variant(p, 'Bandoneon', lambda q: q.flt(1, cutoff=2500).op(2, level=0.5))

def choir(name, f1, f2, pm=0.3, cat=ORCH, attack=0.4):
    p = P(cat, name)
    a = adsr(attack, 0.3, 0.9, 0.5, t=0.2)
    p.op(1, ratio=1, level=1, unison=3, detune=9, spread=0.9, vel=0.3, amp=a).op(2, ratio=1, level=0.6, amp=a).pm(2, 1, pm).fb(2, 0.3)
    p.op(3, ratio=1, fine=-6, level=0.8, unison=2, detune=7, spread=0.9, amp=a).op(4, ratio=2, level=0.4, amp=a).pm(4, 3, pm * 0.7)
    p.op(5, ratio=2, level=0.4, amp=a).op(6, ratio=3, level=0.3, amp=a).pm(6, 5, 0.3).op(7, wave='noise', level=0.06, amp=a).op(8, ratio=0.5, level=0.3, amp=a)
    p.carriers(1, 3, to='F1').out(1, f2=0.8).out(3, f2=0.8).out(5, f3=0.6).out(7, f2=0.5).out(8, dry=0.5)
    p.flt(1, 'BP', cutoff=f1, reso=0.55).flt(2, 'BP', cutoff=f2, reso=0.5).flt(3, 'LP', cutoff=4000)
    vibrato(p, rate=5, delay=0.6, cents=0.08, ops=(1, 3)).chorus(rate=0.3, depth=0.3, mix=0.35).reverb(size=0.85, decay=0.7, mix=0.35)
    return p
choir('Choir Aah', 650, 1100); choir('Choir Ooh', 400, 800, pm=0.2); choir('Choir Mmm', 300, 2500, pm=0.15); choir('Choir Eeh', 350, 2300, pm=0.3)
choir('Boys Choir', 800, 1500, pm=0.2, attack=0.3).op(8, level=0.1); choir('Vocal Pad Oh', 450, 900, pm=0.25, attack=1.2, cat=PAD)

# ============================================================ DUBSTEP BASS ====
# the bass architecture: saw carrier (1 <- 2 with feedback) + its octave (3 <- 4), a formant carrier
# (5, ring-modulated by 6) into filter 2, a sine sub (7) straight to Dry, a transient click (8)
def bass8(p, saw=0.5, fb=0.3, sub=0.6, unison=2, detune=10, formant=0.5, click=0.3):
    a = adsr(0.004, 0.1, 1.0, 0.08)
    p.mono(porta=0.04).bend(12)
    p.op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.5, vel=0.2, amp=a)
    p.op(2, ratio=1, level=0.9, vel=0.2, amp=a).pm(2, 1, saw).fb(2, fb)
    p.op(3, ratio=2, level=0.5, amp=a).op(4, ratio=1, level=0.7, amp=a).pm(4, 3, saw * 0.8).pm(2, 3, 0.15)
    p.op(5, ratio=1, level=formant, amp=a).op(6, ratio=3, level=0.7, amp=a).rm(6, 5, 0.6).pm(6, 5, 0.2)
    p.op(7, ratio=0.5, level=sub, vel=0.1, amp=adsr(0.005, 0.1, 1.0, 0.1))
    p.op(8, ratio=6, level=click, amp=perc(0.001, 0.03)).pm(8, 1, 0.3)
    p.carriers(1, 3, to='F1').out(5, f2=0.8).out(7, dry=0.8)
    return p

DIV_GRID = ['1/2', '1/4', '1/4D', '1/4T', '1/8', '1/8D', '1/8T', '1/16', '1/16T']
LFO_GRID = ['sine', 'tri', 'square', 'saw']
TONE_GRID = {'LP': ('LP', 320, 0.5, 24), 'BP': ('BP', 520, 0.6, 12), 'HP': ('HP', 140, 0.5, 24)}

def wobble(name, div='1/4', lfo='sine', tone='LP', amt=0.45, dirty=False, growl=0.0, phase=0, key=0.2, extra=None, cat=DUB):
    ftype, cutoff, reso, slope = TONE_GRID[tone]
    p = P(cat, name)
    bass8(p)
    p.flt(1, ftype, cutoff=cutoff, reso=reso, slope=slope, drive=0.2, key=key).flt(2, 'BP', cutoff=900, reso=0.55)
    p.lfo(1, lfo, div=div, phase=phase).mod('lfo1', 'flt1Cutoff', amt).mod('lfo1', 'flt2Cutoff', amt * 0.6).mod('lfo1', 'rm65', 0.25)
    if growl: p.mod('lfo1', 'pm21', growl).mod('lfo1', 'pm43', growl * 0.7)
    p.mod('wheel', 'flt1Cutoff', 0.25).mod('wheel', 'pm21', 0.15)
    p.dist('hard' if dirty else 'soft', drive=0.6 if dirty else 0.35, tone=0.85, mix=0.75 if dirty else 0.65)
    p.eq(low=2, lowf=70, lowcut=30).comp(thresh=-14, ratio=4, attack=6, release=80)
    if extra: extra(p)
    return p

for div in DIV_GRID:
    for lfo in LFO_GRID:
        for tone in TONE_GRID:
            tag = div + ' ' + {'sine': 'Sine', 'tri': 'Tri', 'square': 'Square', 'saw': 'Saw'}[lfo] + ' ' + tone
            wobble('Wob ' + tag, div, lfo, tone, amt=0.5 if lfo != 'square' else 0.38)
            wobble('Wob ' + tag + ' Dirty', div, lfo, tone, amt=0.45 if lfo != 'square' else 0.35, dirty=True, growl=0.2)

VOWELS = {'Aa': (650, 1100), 'Oh': (450, 850), 'Ee': (300, 2300), 'Uh': (500, 1000), 'Ow': (350, 700)}
def growl(name, div='1/8', vowel='Aa', dirty=False, rm=0.5, pmamt=0.3, cat=DUB):
    f1, f2 = VOWELS[vowel]
    p = P(cat, name)
    bass8(p, saw=0.45, fb=0.35, unison=1, formant=0.8)
    p.rm(6, 1, rm * 0.5).out(1, f1=0.8, f2=0.8).out(3, f1=0.5, f2=0.5).out(5, f2=0.9, f3=0.6)
    p.flt(1, 'BP', cutoff=f1, reso=0.6, slope=12, drive=0.2).flt(2, 'BP', cutoff=f2, reso=0.6, slope=12, drive=0.2).flt(3, 'LP', cutoff=1800, reso=0.3)
    p.lfo(1, 'sine', div=div).mod('lfo1', 'flt1Cutoff', 0.35).mod('lfo1', 'flt2Cutoff', 0.3).mod('lfo1', 'pm21', pmamt).mod('lfo1', 'rm65', 0.3)
    p.lfo(2, 'tri', div='1/1').mod('lfo2', 'flt3Cutoff', 0.25).mod('wheel', 'pm21', 0.2).mod('wheel', 'rm61', 0.3)
    p.dist('hard' if dirty else 'fold', drive=0.6 if dirty else 0.5, tone=0.8, mix=0.75).eq(low=3, lowf=60, lowcut=30, mid=2, midf=900).comp(thresh=-14, ratio=5, attack=5, release=70)
    return p
for vowel in VOWELS:
    for div in ('1/4', '1/4D', '1/8', '1/8D', '1/8T', '1/16'):
        growl('Growl %s %s' % (vowel, div), div, vowel)
        growl('Growl %s %s Dirty' % (vowel, div), div, vowel, dirty=True, pmamt=0.4)

def dub_special(name, fn):
    p = P(DUB, name)
    fn(p)
    return p
dub_special('Reese Wide', lambda p: (bass8(p, unison=6, detune=22, saw=0.5), p.flt(1, 'LP', cutoff=600, reso=0.2, slope=24).flt(2, 'BP', cutoff=800, reso=0.4).mod('wheel', 'flt1Cutoff', 0.4)
    .dist('soft', drive=0.4, tone=0.8, mix=0.6).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=8)))
for n, uni in ((2, 2), (4, 4), (8, 8)):
    for tone, cut in (('Dark', 350), ('Mid', 700), ('Bright', 1600)):
        dub_special('Reese %d-voice %s' % (n, tone), lambda p, uni=uni, cut=cut: (bass8(p, unison=uni, detune=24, saw=0.5), p.flt(1, 'LP', cutoff=cut, reso=0.25, slope=24).flt(2, 'BP', cutoff=900, reso=0.4)
            .lfo(1, 'sine', div='1/1').mod('lfo1', 'flt1Cutoff', 0.15).mod('wheel', 'flt1Cutoff', 0.4).dist('soft', drive=0.35, tone=0.8, mix=0.6).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=8)))
for div in ('1/4', '1/8', '1/8T', '1/16'):
    dub_special('Neuro Grind ' + div, lambda p, div=div: (bass8(p, saw=0.5, fb=0.45, unison=3, detune=15), p.rm(4, 1, 0.4).pm(6, 3, 0.3)
        .flt(1, 'BP', cutoff=700, reso=0.55, slope=12, drive=0.4).flt(2, 'BP', cutoff=1600, reso=0.5).lfo(1, 'tri', div=div).mod('lfo1', 'flt1Cutoff', 0.3).mod('lfo1', 'flt2Cutoff', -0.25)
        .lfo(2, 'sine', div='1/2').mod('lfo2', 'pm43', 0.3).mod('lfo2', 'rm65', 0.3).mod('wheel', 'flt1Cutoff', 0.3)
        .phaser(rate=0.2, depth=0.8, stages=2, feedback=0.6, mix=0.5).dist('hard', drive=0.55, tone=0.75, mix=0.8).eq(low=3, lowf=60, lowcut=30, mid=3, midf=1500).comp(thresh=-16, ratio=6, attack=4)))
    dub_special('Screech ' + div, lambda p, div=div: (bass8(p, saw=0.55, fb=0.5, unison=1), p.op(6, ratio=7).pm(6, 2, 0.4)
        .flt(1, 'LP', cutoff=1200, reso=0.75, slope=12).flt(2, 'BP', cutoff=2500, reso=0.6).lfo(1, 'sine', div=div).mod('lfo1', 'flt1Cutoff', 0.4).mod('lfo1', 'pm62', 0.25).mod('wheel', 'pm62', 0.3)
        .dist('hard', drive=0.6, tone=0.9, mix=0.8).eq(low=2, lowf=60, lowcut=30, high=2, highf=4000).comp(thresh=-16, ratio=6, attack=4)))
    dub_special('Yoy ' + div, lambda p, div=div: (bass8(p, saw=0.45, fb=0.3), p.op(1, pitch=pitch_drop(0.75, 0.15), pitchamt=12).op(3, pitch=pitch_drop(0.75, 0.15), pitchamt=12)
        .flt(1, 'LP', cutoff=500, reso=0.6, slope=24).flt(2, 'BP', cutoff=1200, reso=0.6).lfo(1, 'sine', div=div).mod('lfo1', 'flt1Cutoff', 0.45).mod('lfo1', 'flt2Cutoff', -0.35).mod('lfo1', 'op5Fine', 0.2)
        .dist('fold', drive=0.45, tone=0.85, mix=0.7).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)))
    dub_special('Trip Gate ' + div, lambda p, div=div: (bass8(p), p.flt(1, 'LP', cutoff=500, reso=0.45, slope=24).flt(2, 'BP', cutoff=900, reso=0.5)
        .lfo(1, 'square', div=div).mod('lfo1', 'op1Level', -0.5).mod('lfo1', 'op3Level', -0.5).mod('lfo1', 'op5Level', -0.5)
        .lfo(2, 'sine', div='1/2').mod('lfo2', 'flt1Cutoff', 0.35).dist('soft', drive=0.35, tone=0.85, mix=0.6).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=5)))
    dub_special('Sub + Wob ' + div, lambda p, div=div: (bass8(p, sub=0.9), p.op(7, level=0.9).out(7, dry=1.0).out(1, f1=0.6).flt(1, 'LP', cutoff=400, reso=0.5, slope=24).flt(2, 'BP', cutoff=800, reso=0.5)
        .lfo(1, 'sine', div=div).mod('lfo1', 'flt1Cutoff', 0.45).dist('soft', drive=0.3, tone=0.8, mix=0.5).eq(low=1, lowf=50, lowcut=25).comp(thresh=-12, ratio=4, attack=8)))
    dub_special('Laser Bass ' + div, lambda p, div=div: (bass8(p, saw=0.4), p.op(6, ratio=5, pitch=pitch_drop(1.0, 0.12), pitchamt=24).flt(1, 'LP', cutoff=500, reso=0.65, slope=24).flt(2, 'BP', cutoff=1500, reso=0.6)
        .lfo(1, 'sine', div=div).mod('lfo1', 'flt1Cutoff', 0.4).mod('lfo1', 'pm65', 0.25).dist('soft', drive=0.4, tone=0.9, mix=0.7).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)))
dub_special('Hoover Bass', lambda p: (bass8(p, unison=6, detune=30, saw=0.5, fb=0.35), p.op(1, pitch=pitch_drop(0.25, 0.4), pitchamt=12).op(2, pitch=pitch_drop(0.25, 0.4), pitchamt=12).op(3, pitch=pitch_drop(0.25, 0.4), pitchamt=12)
    .flt(1, 'LP', cutoff=2500, reso=0.2, slope=12).flt(2, 'BP', cutoff=1200, reso=0.4).lfo(1, 'sine', div='1/4').mod('lfo1', 'flt1Cutoff', 0.2).chorus(rate=0.5, depth=0.4, mix=0.4).dist('soft', drive=0.3, mix=0.5).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=8)))
dub_special('Riddim Square', lambda p: (bass8(p, saw=0.35), p.op(1, partials=[1, 0, 0.33, 0, 0.2, 0, 0.14, 0, 0.11, 0, 0.09]).op(3, partials=[1, 0, 0.33, 0, 0.2])
    .flt(1, 'LP', cutoff=500, reso=0.6, slope=24).flt(2, 'BP', cutoff=1000, reso=0.6).lfo(1, 'square', div='1/16').mod('lfo1', 'flt1Cutoff', 0.35).mod('lfo1', 'pm21', 0.25)
    .dist('hard', drive=0.5, tone=0.85, mix=0.8).eq(low=3, lowf=60, lowcut=30, mid=2, midf=1200).comp(thresh=-16, ratio=6, attack=3)))
dub_special('Wob Drop Siren', lambda p: (bass8(p), p.op(1, pitch=env([[0, 0.5], [2, 0.5], [6, 0.25, 0.2], [7, 0.25]], sustain=3, sync=True), pitchamt=24)
    .op(3, pitch=env([[0, 0.5], [2, 0.5], [6, 0.25, 0.2], [7, 0.25]], sustain=3, sync=True), pitchamt=24).op(2, pitch=env([[0, 0.5], [2, 0.5], [6, 0.25, 0.2], [7, 0.25]], sustain=3, sync=True), pitchamt=24)
    .flt(1, 'LP', cutoff=450, reso=0.5, slope=24).flt(2, 'BP', cutoff=900, reso=0.5).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.45).dist('soft', drive=0.4, tone=0.85, mix=0.65).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)))
dub_special('Wob Drawn Stutter', lambda p: (bass8(p), p.flt(1, 'LP', cutoff=400, reso=0.5, slope=24).flt(2, 'BP', cutoff=900, reso=0.5)
    .lfo(1, 'drawn', div='1/8', shape=[1] * 8 + [-1] * 8 + [1] * 8 + [-1] * 8 + [1] * 16 + [-1] * 16).mod('lfo1', 'flt1Cutoff', 0.45).mod('lfo1', 'rm65', 0.3)
    .dist('soft', drive=0.35, tone=0.85, mix=0.65).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)))
dub_special('Wob S&H Random', lambda p: (bass8(p), p.flt(1, 'LP', cutoff=400, reso=0.55, slope=24).flt(2, 'BP', cutoff=900, reso=0.5)
    .lfo(1, 'sh', div='1/16').mod('lfo1', 'flt1Cutoff', 0.4).mod('lfo1', 'flt2Cutoff', 0.3).mod('lfo1', 'pm43', 0.2).dist('soft', drive=0.4, tone=0.85, mix=0.65).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)))
dub_special('Tearout Rip', lambda p: (bass8(p, saw=0.55, fb=0.5, unison=2, detune=18), p.rm(2, 1, 0.3).flt(1, 'HP', cutoff=150, reso=0.5, slope=24, drive=0.5).flt(2, 'BP', cutoff=1800, reso=0.6)
    .lfo(1, 'tri', div='1/8').mod('lfo1', 'flt1Cutoff', 0.55).mod('lfo1', 'pm21', 0.35).mod('lfo1', 'flt2Cutoff', -0.3)
    .dist('hard', drive=0.7, tone=0.8, mix=0.85).eq(low=3, lowf=70, lowcut=35, mid=3, midf=2500, q=0.8).comp(thresh=-18, ratio=8, attack=3, release=60)))
dub_special('Brostep Yell', lambda p: (bass8(p, saw=0.5, fb=0.4), p.out(1, f1=0.8, f2=0.8).flt(1, 'BP', cutoff=700, reso=0.6).flt(2, 'BP', cutoff=2200, reso=0.55)
    .lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.45).mod('lfo1', 'flt2Cutoff', 0.35).lfo(2, 'square', div='1/4').mod('lfo2', 'pm43', 0.25).mod('wheel', 'flt2Cutoff', 0.3)
    .dist('fold', drive=0.5, tone=0.85, mix=0.8).eq(low=3, lowf=60, lowcut=30).comp(thresh=-16, ratio=6, attack=4)))
dub_special('Clean Wob Sine', lambda p: (p.mono(porta=0.04).op(1, ratio=1, level=1, amp=adsr(0.004, 0.1, 1, 0.08)).op(2, ratio=1, level=0.7, amp=adsr(0.004, 0.1, 1, 0.08)).pm(2, 1, 0.3)
    .op(3, ratio=2, level=0.4, amp=adsr(0.004, 0.1, 1, 0.08)).op(4, ratio=2, level=0.5, amp=adsr(0.004, 0.1, 1, 0.08)).pm(4, 3, 0.3).op(7, ratio=0.5, level=0.7, amp=adsr(0.005, 0.1, 1, 0.1))
    .carriers(1, 3, to='F1').out(7, dry=0.8).flt(1, 'LP', cutoff=600, reso=0.3, slope=12).lfo(1, 'sine', div='1/4').mod('lfo1', 'pm21', 0.3).mod('lfo1', 'pm43', 0.3).mod('lfo1', 'flt1Cutoff', 0.3).eq(low=2, lowf=60).comp(thresh=-12, ratio=3, attack=8)))
dub_special('Growl Pad Bass', lambda p: (bass8(p, unison=3, detune=12), [p.op(k, amp=adsr(0.15, 0.2, 1, 0.3)) for k in range(1, 7)],
    p.flt(1, 'LP', cutoff=500, reso=0.4, slope=24).flt(2, 'BP', cutoff=900, reso=0.5).lfo(1, 'sine', div='1/2').mod('lfo1', 'flt1Cutoff', 0.4).mod('lfo1', 'pm21', 0.2).mod('lfo1', 'rm65', 0.3)
    .chorus(rate=0.3, depth=0.3, mix=0.3).dist('soft', drive=0.3, mix=0.5).reverb(size=0.5, decay=0.4, mix=0.15).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=8)))
dub_special('Formant Sweep', lambda p: (bass8(p, unison=1), p.out(1, f1=0.9, f2=0.5).flt(1, 'BP', cutoff=300, reso=0.7, slope=12).flt(2, 'BP', cutoff=1200, reso=0.6)
    .lfo(1, 'sine', div='1/4').mod('lfo1', 'flt1Cutoff', 0.6).mod('lfo1', 'flt2Cutoff', 0.4).mod('wheel', 'flt1Cutoff', 0.3).dist('soft', drive=0.4, tone=0.8, mix=0.6).eq(low=3, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)))
dub_special('Metal Growl', lambda p: (bass8(p, saw=0.5, fb=0.45, unison=1), p.rm(6, 1, 0.5).rm(4, 3, 0.4).out(1, f1=0.8, f2=0.6).flt(1, 'BP', cutoff=600, reso=0.6).flt(2, 'BP', cutoff=2000, reso=0.6)
    .lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.35).mod('lfo1', 'flt2Cutoff', 0.35).mod('lfo1', 'rm61', 0.3).dist('hard', drive=0.6, tone=0.8, mix=0.8).eq(low=3, lowf=60, lowcut=30).comp(thresh=-14, ratio=5, attack=5)))
dub_special('Octave Jump Wob', lambda p: (bass8(p), p.flt(1, 'LP', cutoff=450, reso=0.5, slope=24).flt(2, 'BP', cutoff=900, reso=0.5).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.4)
    .lfo(2, 'square', div='1/2').mod('lfo2', 'op3Level', 0.5).mod('lfo2', 'pm43', 0.2).dist('soft', drive=0.4, tone=0.85, mix=0.65).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)))
dub_special('Phased Wob', lambda p: (bass8(p), p.flt(1, 'LP', cutoff=380, reso=0.5, slope=24).flt(2, 'BP', cutoff=900, reso=0.5).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.4)
    .phaser(rate=0.3, depth=0.6, stages=2, feedback=0.5, mix=0.4).dist('soft', drive=0.35, tone=0.85, mix=0.65).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)))
dub_special('Ping-pong Wob', lambda p: (bass8(p), p.flt(1, 'LP', cutoff=380, reso=0.5, slope=24).flt(2, 'BP', cutoff=900, reso=0.5).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.45)
    .delay(div='1/8', feedback=0.3, pingpong=True, tone=0.4, mix=0.18).dist('soft', drive=0.35, tone=0.85, mix=0.65).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)))
dub_special('Two LFO Poly Wob', lambda p: (bass8(p), p.flt(1, 'LP', cutoff=380, reso=0.5, slope=24).flt(2, 'BP', cutoff=900, reso=0.5).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.35)
    .lfo(2, 'sine', div='1/4D').mod('lfo2', 'flt1Cutoff', 0.25).mod('lfo2', 'flt2Cutoff', 0.3).dist('soft', drive=0.35, tone=0.85, mix=0.65).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)))
dub_special('Pitch Bend Wob', lambda p: (bass8(p), p.flt(1, 'LP', cutoff=400, reso=0.5, slope=24).flt(2, 'BP', cutoff=900, reso=0.5).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.4).mod('lfo1', 'op1Fine', 0.12).mod('lfo1', 'op2Fine', 0.12).mod('lfo1', 'op3Fine', 0.12)
    .dist('soft', drive=0.35, tone=0.85, mix=0.6).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)))
dub_special('Dirty Octaves Wob', lambda p: (bass8(p), p.op(3, level=0.8).flt(1, 'LP', cutoff=380, reso=0.5, slope=24).flt(2, 'BP', cutoff=900, reso=0.5).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.45)
    .dist('crush', drive=0.45, tone=0.7, mix=0.6).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=5, attack=5)))

# ------------------------------------------------------------------ BASS -----
def sub(name, drive=0.0, decay=None, harmonic=0.0, pitch=None, cat=BASS):
    p = P(cat, name)
    a = adsr(0.005, 0.1, 1, 0.12) if decay is None else perc(0.003, decay)
    p.op(1, ratio=1, level=1, vel=0.3, amp=a, pitch=pitch, pitchamt=36 if pitch else None)
    p.op(2, ratio=1, level=0.6, amp=a).pm(2, 1, harmonic)
    p.op(3, ratio=2, level=0.3, amp=a).op(4, ratio=2, level=0.5, amp=a).pm(4, 3, harmonic * 0.8)
    p.op(5, ratio=0.5, level=0.3, amp=a).op(6, ratio=1, level=0.3, amp=a).fb(6, 0.3).pm(6, 2, 0.2)
    p.op(7, ratio=3, level=0.3, amp=perc(0.001, 0.04)).pm(7, 1, 0.2).op(8, wave='noise', level=0.1, amp=perc(0.001, 0.01))
    p.mono(porta=0.03).carriers(1, 3, to='F1').out(5, dry=0.6).out(8, dry=0.3).flt(1, 'LP', cutoff=600, reso=0.2, slope=24).eq(low=1, lowf=50, lowcut=25).comp(thresh=-10, ratio=3, attack=10)
    if drive: p.dist('soft', drive=drive, tone=0.4, mix=0.6)
    return p
sub('Sub Sine'); sub('Sub Harmonic', harmonic=0.25, drive=0.15); sub('Sub Warm', harmonic=0.15).flt(1, cutoff=300)
sub('808 Sub', decay=1.8, drive=0.25, pitch=pitch_drop(0.8, 0.06)); sub('808 Short', decay=0.6, drive=0.2, pitch=pitch_drop(0.85, 0.04))
sub('808 Distorted', decay=1.6, drive=0.6, harmonic=0.3, pitch=pitch_drop(0.85, 0.05)).eq(mid=3, midf=120, q=1.5)
sub('808 Long Tail', decay=3.0, drive=0.3, pitch=pitch_drop(0.8, 0.07)); sub('808 Saturated', decay=1.4, drive=0.8, harmonic=0.35, pitch=pitch_drop(0.85, 0.05)).flt(1, cutoff=900)

def synbass(name, saw=0.5, fb=0.3, cutoff=800, reso=0.2, env_=0.4, decay=0.3, sustain=0.7, unison=1, detune=20, drive=0.0, porta=0.03, extra=None, cat=BASS):
    p = P(cat, name)
    a = adsr(0.004, decay, sustain, 0.12)
    p.mono(porta=porta).op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.6, amp=a).op(2, ratio=1, level=0.9, amp=a).pm(2, 1, saw).fb(2, fb)
    p.op(3, ratio=2, level=0.5, amp=a).op(4, ratio=1, level=0.6, amp=a).pm(4, 3, saw * 0.7).pm(2, 3, 0.1)
    p.op(5, ratio=0.5, level=0.6, amp=a).op(6, ratio=3, level=0.4, amp=a).pm(6, 2, 0.2).fb(6, 0.2)
    p.op(7, ratio=4, level=0.4, vel=1, amp=perc(0.001, 0.05)).pm(7, 1, 0.25).op(8, wave='noise', level=0.1, amp=perc(0.001, 0.01))
    p.carriers(1, 3, to='F1').out(5, dry=0.8).out(8, f2=0.5).flt(1, 'LP', cutoff=cutoff, reso=reso, slope=24, env=env_, vel=0.3, key=0.3, cut=perc(0.002, 0.3)).flt(2, 'HP', cutoff=2000)
    if drive: p.dist('soft', drive=drive, tone=0.8, mix=0.6)
    p.eq(low=2, lowf=70, lowcut=30).comp(thresh=-12, ratio=4, attack=8)
    if extra: extra(p)
    return p
synbass('Reese Classic', unison=2, detune=24, cutoff=800, env_=0.0, sustain=1.0)
synbass('Acid Squelch', cutoff=300, reso=0.8, env_=0.55, decay=0.2, drive=0.3, extra=lambda p: p.mod('wheel', 'flt1Cutoff', 0.4).delay(div='1/8D', feedback=0.3, pingpong=True, tone=0.5, mix=0.15))
synbass('Acid Deep', cutoff=200, reso=0.85, env_=0.6, decay=0.3, drive=0.2, extra=lambda p: p.mod('wheel', 'flt1Cutoff', 0.5))
synbass('Acid Screamer', cutoff=500, reso=0.9, env_=0.7, decay=0.15, drive=0.5, extra=lambda p: p.mod('wheel', 'flt1Cutoff', 0.4))
synbass('Moog Ladder', cutoff=450, reso=0.45, env_=0.4, decay=0.3, sustain=0.8, porta=0.06)
synbass('Moog Deep', cutoff=250, reso=0.35, env_=0.3, decay=0.4, sustain=0.9, porta=0.08)
synbass('Square Bass', saw=0.0, cutoff=900, reso=0.3, env_=0.3, extra=lambda p: p.op(1, partials=[1, 0, 0.33, 0, 0.2, 0, 0.14, 0, 0.11]).op(3, partials=[1, 0, 0.33, 0, 0.2]))
synbass('Pluck Bass', cutoff=600, reso=0.3, env_=0.4, decay=0.6, sustain=0.0)
synbass('Pluck Bass Bright', cutoff=1200, reso=0.3, env_=0.5, decay=0.5, sustain=0.0)
synbass('Deep House Bass', cutoff=500, reso=0.25, env_=0.3, decay=0.3, sustain=0.6)
synbass('Garage Bass', cutoff=700, reso=0.4, env_=0.35, decay=0.3, sustain=0.5, porta=0.02)
synbass('DnB Reese Dark', unison=3, detune=28, cutoff=380, reso=0.3, env_=0.0, sustain=1.0, drive=0.35, porta=0.05, extra=lambda p: p.mod('wheel', 'flt1Cutoff', 0.4))
synbass('Techno Rumble', cutoff=180, reso=0.4, env_=0.0, drive=0.5, extra=lambda p: p.reverb(size=0.6, decay=0.5, damp=0.8, mix=0.25))
synbass('Sync Lead Bass', cutoff=1500, reso=0.3, env_=0.2, drive=0.4, extra=lambda p: p.op(6, ratio=3, mod=env([[0, 1], [0.3, 0.5, -0.5], [1, 0.5]], sustain=2), modamt=0.8).pm(6, 1, 0.35))
synbass('Hoover Bass Lite', unison=4, detune=28, cutoff=2000, env_=0.0, sustain=1.0, extra=lambda p: p.op(1, pitch=pitch_drop(0.25, 0.4), pitchamt=12).op(2, pitch=pitch_drop(0.25, 0.4), pitchamt=12).chorus(rate=0.5, depth=0.4, mix=0.4))
synbass('Wobble Lite 1/4', cutoff=600, reso=0.3, env_=0.0, sustain=1.0, extra=lambda p: p.lfo(1, 'sine', div='1/4').mod('lfo1', 'flt1Cutoff', 0.3))
synbass('Wobble Lite 1/8', cutoff=600, reso=0.3, env_=0.0, sustain=1.0, extra=lambda p: p.lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.3))
synbass('Wobble Lite 1/16', cutoff=600, reso=0.35, env_=0.0, sustain=1.0, extra=lambda p: p.lfo(1, 'tri', div='1/16').mod('lfo1', 'flt1Cutoff', 0.3))
synbass('Trance Bass', cutoff=900, reso=0.2, env_=0.3, decay=0.2, sustain=0.0, extra=lambda p: p.op(1, amp=adsr(0.002, 0.18, 0.0, 0.05)))
synbass('Psy Bass', cutoff=1200, reso=0.3, env_=0.4, decay=0.12, sustain=0.0, drive=0.3, extra=lambda p: [p.op(k, amp=adsr(0.001, 0.1, 0.0, 0.03)) for k in (1, 2, 3, 4, 5)])
synbass('Electro Bass', saw=0.55, fb=0.4, cutoff=1500, reso=0.4, env_=0.5, decay=0.25, sustain=0.3, drive=0.4)
synbass('Dark Techno Bass', cutoff=300, reso=0.5, env_=0.2, drive=0.4, extra=lambda p: p.lfo(1, 'sine', div='1/2').mod('lfo1', 'flt1Cutoff', 0.15))
synbass('Funk FM Bass', saw=0.5, cutoff=3000, env_=0.5, decay=0.5, sustain=0.3, porta=0.015, extra=lambda p: p.op(7, level=0.6).eq(mid=2, midf=1800))
synbass('FM Slap', saw=0.55, cutoff=4000, env_=0.5, decay=0.4, sustain=0.5, porta=0.02, extra=lambda p: p.op(7, ratio=4, level=0.6, amp=perc(0.001, 0.06)).pm(7, 1, 0.35))
synbass('Organ Bass', saw=0.0, cutoff=5000, env_=0.0, sustain=1.0, extra=lambda p: p.op(3, level=0.6).out(3, f1=0.7).op(5, level=0.7).dist('soft', drive=0.2, mix=0.4))
synbass('Donk', cutoff=2000, env_=0.0, decay=0.35, sustain=0.0, drive=0.3, extra=lambda p: p.op(1, pitch=pitch_drop(0.75, 0.05), pitchamt=12).op(3, pitch=pitch_drop(0.75, 0.05), pitchamt=12).eq(mid=3, midf=400))
synbass('Trap 808 Long', cutoff=400, env_=0.1, decay=2.5, sustain=0.4, drive=0.4, porta=0.08, extra=lambda p: p.op(1, pitch=pitch_drop(0.8, 0.05), pitchamt=36).op(5, pitch=pitch_drop(0.8, 0.05), pitchamt=36).comp(thresh=-10, ratio=4, attack=10, limit=True))
for nm in ('Reese Classic', 'Moog Ladder', 'Pluck Bass', 'Deep House Bass', 'Electro Bass', 'Funk FM Bass'):
    variant(next(x for x in PRESETS if x.name == nm), 'Octave Down', mod_oct_down)
    variant(next(x for x in PRESETS if x.name == nm), 'Dirty', mod_dirty)
for nm in ('Acid Squelch', 'Garage Bass', 'Trance Bass', 'Square Bass'):
    variant(next(x for x in PRESETS if x.name == nm), 'Echo', mod_echo)

# ------------------------------------------------------------------ LEADS ----
# lead architecture: main carrier (1 <- 2 <- 3 stack with feedback on 2), octave carrier (4 <- 5),
# a ring cell (6 x 1) for bite, a sub (7), breath noise (8) into filter 2
def lead(name, pm=0.5, fb=0.25, unison=1, detune=10, ratio3=3, pm3=0.25, cutoff=4000, reso=0.15, attack=0.01, porta=0.05,
         legato_=True, vib=0.1, drive=0.0, delay=True, ring=0.0, extra=None, cat=LEAD):
    p = P(cat, name)
    a = adsr(attack, 0.2, 0.85, 0.15)
    p.op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.7, vel=0.3, amp=a)
    p.op(2, ratio=1, level=0.85, vel=0.5, amp=a).pm(2, 1, pm).fb(2, fb)
    p.op(3, ratio=ratio3, level=0.5, amp=a).pm(3, 2, pm3).pm(3, 1, pm3 * 0.4)
    p.op(4, ratio=2, level=0.45, unison=max(1, unison // 2), detune=detune, spread=0.7, amp=a).op(5, ratio=2, level=0.6, amp=a).pm(5, 4, pm * 0.7)
    p.op(6, ratio=1.5, level=0.5, amp=a).rm(6, 1, ring)
    p.op(7, ratio=0.5, level=0.35, amp=a).op(8, wave='noise', level=0.08, amp=adsr(0.01, 0.2, 0.3, 0.1))
    p.carriers(1, 4, to='F1').out(7, dry=0.6).out(8, f2=1).flt(2, 'BP', cutoff=3000, reso=0.4)
    p.flt(1, 'LP', cutoff=cutoff, reso=reso, key=0.4, vel=0.3, env=0.2, cut=adsr(0.005, 0.4, 0.5, 0.2))
    if legato_: p.legato(porta)
    if vib: vibrato(p, rate=5.5, delay=0.4, cents=vib, ops=(1, 2, 4))
    p.mod('wheel', 'rm61', 0.4)
    if drive: p.dist('soft', drive=drive, tone=0.85, mix=0.6)
    if delay: p.delay(div='1/8D', feedback=0.3, pingpong=True, tone=0.5, mix=0.18)
    p.reverb(size=0.5, decay=0.45, mix=0.14).comp(thresh=-14, ratio=3, attack=8)
    if extra: extra(p)
    return p
LEADS = [
    ('Supersaw Lead', dict(unison=8, detune=18, pm=0.5, fb=0.3, cutoff=6000, legato_=False, vib=0.0, extra=lambda p: p.chorus(rate=0.4, depth=0.3, mix=0.3))),
    ('Trance Lead', dict(unison=4, detune=14, cutoff=5000, legato_=False, extra=lambda p: p.chorus(rate=0.5, depth=0.25, mix=0.25))),
    ('Hoover Lead', dict(unison=6, detune=32, pm=0.5, fb=0.35, cutoff=3500, legato_=False, vib=0.0, extra=lambda p: [p.op(k, pitch=pitch_drop(0.2, 0.5), pitchamt=12) for k in (1, 2, 4, 5)] and p.chorus(rate=0.6, depth=0.4, mix=0.4))),
    ('Square Lead', dict(pm=0.0, pm3=0.0, extra=lambda p: p.op(1, partials=[1, 0, 0.33, 0, 0.2, 0, 0.14, 0, 0.11, 0, 0.09, 0, 0.08]).op(4, partials=[1, 0, 0.33, 0, 0.2]))),
    ('Sync Lead', dict(pm=0.45, fb=0.35, ratio3=4, pm3=0.3, extra=lambda p: p.op(3, mod=env([[0, 1], [0.4, 0.5, -0.5], [1, 0.5]], sustain=2), modamt=0.9))),
    ('Dubstep Screech Lead', dict(pm=0.55, fb=0.5, ratio3=7, pm3=0.35, cutoff=2500, reso=0.6, drive=0.5, ring=0.3, extra=lambda p: p.lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.4).mod('lfo1', 'pm32', 0.25))),
    ('Growl Lead', dict(pm=0.5, fb=0.4, ratio3=2, pm3=0.3, cutoff=1500, reso=0.5, drive=0.45, ring=0.2, extra=lambda p: p.lfo(1, 'tri', div='1/16').mod('lfo1', 'pm21', 0.3).mod('lfo1', 'flt1Cutoff', 0.3))),
    ('Talkbox Lead', dict(pm=0.45, cutoff=900, reso=0.65, extra=lambda p: p.out(1, f2=0.8).flt(2, 'BP', cutoff=1800, reso=0.6).mod('wheel', 'flt1Cutoff', 0.5).mod('wheel', 'flt2Cutoff', -0.3))),
    ('Brass Lead', dict(pm=0.5, fb=0.2, attack=0.04, cutoff=3500, extra=lambda p: p.op(2, mod=swell(0.15, 0.3, 0.6)))),
    ('Sine Lead', dict(pm=0.08, pm3=0.05, cutoff=8000, vib=0.12)),
    ('Whistle Lead', dict(pm=0.05, ratio3=3, pm3=0.05, cutoff=9000, vib=0.15, extra=lambda p: p.op(1, ratio=2).op(2, ratio=2).op(4, ratio=4))),
    ('Portamento Glide', dict(pm=0.4, porta=0.18, vib=0.08)),
    ('Acid Lead', dict(pm=0.5, fb=0.3, cutoff=800, reso=0.75, drive=0.3, extra=lambda p: p.flt(1, env=0.5, cut=perc(0.001, 0.3)).mod('wheel', 'flt1Cutoff', 0.4))),
    ('Neuro Lead', dict(pm=0.5, fb=0.45, ratio3=3, pm3=0.3, cutoff=2000, reso=0.4, drive=0.5, ring=0.3, extra=lambda p: p.phaser(rate=0.25, depth=0.7, stages=2, feedback=0.5, mix=0.4).lfo(1, 'sine', div='1/4').mod('lfo1', 'pm21', 0.2))),
    ('Bell Lead', dict(pm=0.35, ratio3=3.5, pm3=0.3, cutoff=8000, legato_=False, vib=0.0, attack=0.002, extra=lambda p: p.op(1, amp=adsr(0.002, 2.0, 0.3, 0.4, t=-0.6)).op(4, amp=adsr(0.002, 1.5, 0.3, 0.4, t=-0.6)).op(3, amp=perc(0.002, 1.2)))),
    ('Distorted Lead', dict(pm=0.5, fb=0.35, drive=0.7, cutoff=3000, extra=lambda p: p.dist('hard', drive=0.6, tone=0.8, mix=0.8))),
    ('Vocal Lead', dict(pm=0.4, cutoff=700, reso=0.6, extra=lambda p: p.out(1, f2=0.9).flt(2, 'BP', cutoff=2400, reso=0.55).lfo(3, 'sine', rate=0.5).mod('lfo3', 'flt1Cutoff', 0.2).mod('lfo3', 'flt2Cutoff', -0.15))),
    ('Chip Lead', dict(pm=0.0, pm3=0.0, vib=0.15, delay=False, extra=lambda p: p.op(1, partials=[1, 0, 0.33, 0, 0.2, 0, 0.14, 0, 0.11]).flt(1, cutoff=9000).op(1, amp=adsr(0.001, 0.05, 1, 0.02)).op(4, partials=[1, 0, 0.33, 0, 0.2], level=0.5))),
    ('Riff Lead', dict(pm=0.5, fb=0.25, cutoff=3000, drive=0.3, porta=0.03, extra=lambda p: p.mod('vel', 'flt1Cutoff', 0.3))),
    ('303 Lead', dict(pm=0.5, fb=0.3, cutoff=600, reso=0.8, porta=0.04, extra=lambda p: p.flt(1, env=0.6, cut=perc(0.001, 0.22)).mod('wheel', 'flt1Cutoff', 0.5).delay(div='1/16', feedback=0.4, pingpong=True, tone=0.4, mix=0.2))),
    ('Lo-fi Lead', dict(pm=0.4, cutoff=3000, extra=lambda p: p.dist('crush', drive=0.35, tone=0.6, mix=0.7))),
    ('FM Bright Lead', dict(pm=0.6, fb=0.3, pm3=0.3, cutoff=8000, legato_=False)),
    ('Wobble Lead', dict(pm=0.45, fb=0.3, cutoff=2000, reso=0.5, extra=lambda p: p.lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.45))),
    ('Fifths Lead', dict(pm=0.45, cutoff=4500, extra=lambda p: p.op(6, level=0.8).rm(6, 1, 0.0).out(6, f1=0.8))),
    ('Pluck Lead', dict(pm=0.5, cutoff=5000, legato_=False, vib=0.0, extra=lambda p: [p.op(k, amp=adsr(0.002, 0.5, 0.2, 0.2, t=-0.6)) for k in (1, 2, 3, 4, 5)])),
    ('Glass Lead', dict(pm=0.3, ratio3=5, pm3=0.2, cutoff=9000, vib=0.06, extra=lambda p: p.op(4, level=0.6).chorus(rate=0.3, depth=0.25, mix=0.3))),
    ('Organ Lead', dict(pm=0.0, pm3=0.0, vib=0.0, extra=lambda p: p.op(3, level=0.0).op(4, level=0.7).op(6, level=0.5).out(6, f1=0.6).dist('soft', drive=0.3, mix=0.5))),
    ('Saw Lead Classic', dict(pm=0.5, fb=0.3, cutoff=3500, vib=0.08)),
    ('Trumpet Lead', dict(pm=0.55, fb=0.2, attack=0.05, cutoff=4500, vib=0.08, extra=lambda p: p.op(2, mod=swell(0.1, 0.3, 0.65)).op(5, mod=swell(0.1, 0.3, 0.6)))),
    ('Psy Lead', dict(pm=0.5, fb=0.3, cutoff=2500, reso=0.5, drive=0.3, legato_=False, vib=0.0, extra=lambda p: [p.op(k, amp=adsr(0.001, 0.15, 0.0, 0.05)) for k in (1, 2, 3, 4, 5)] and p.flt(1, env=0.5, cut=perc(0.001, 0.12)))),
]
for nm, kw in LEADS:
    base = lead(nm, **kw)
    variant(base, 'Wide', mod_wide)
    variant(base, 'Dirty', mod_dirty)
    variant(base, 'Octave Down', mod_oct_down)

# ------------------------------------------------------------------- PADS ----
# pad architecture: three detuned carriers (1, 3, 5) with their own modulators (2, 4, 6), a fifth or
# octave carrier (7), a slow modulator (8) feeding 2 and 4 so the index drifts; carriers split F1 / F2
def pad(name, pm=0.3, fb=0.2, unison=4, detune=12, attack=0.8, release=1.2, cutoff=2500, ratio7=2, pm7=0.15, extra=None, cat=PAD):
    p = P(cat, name)
    a = adsr(attack, 0.5, 0.9, release, t=0.2)
    p.op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.9, vel=0.3, amp=a).op(2, ratio=1, level=0.7, vel=0.4, amp=a).pm(2, 1, pm).fb(2, fb)
    p.op(3, ratio=1, fine=-8, level=0.8, unison=max(1, unison - 2), detune=detune, spread=0.9, amp=a).op(4, ratio=2, level=0.5, amp=a).pm(4, 3, pm * 0.8)
    p.op(5, ratio=2, fine=5, level=0.5, amp=adsr(attack * 1.5, 0.5, 0.8, release, t=0.2)).op(6, ratio=3, level=0.4, amp=a).pm(6, 5, pm * 0.6)
    p.op(7, ratio=ratio7, level=0.5, unison=2, detune=8, spread=0.8, amp=a).pm(2, 7, pm7)
    p.op(8, ratio=0.5, level=0.4, amp=adsr(attack * 2, 0.5, 0.9, release)).pm(8, 2, 0.2).pm(8, 4, 0.15)
    p.carriers(1, 3, to='F1').out(5, f2=0.7).out(7, f1=0.6).out(8, dry=0.3)
    p.flt(1, 'LP', cutoff=cutoff, key=0.3, vel=0.2, env=0.3, cut=env([[0, 0], [2.5, 1, 0.2], [5, 0.5, -0.3], [6, 0, -0.5]], sustain=2)).flt(2, 'LP', cutoff=cutoff * 2, key=0.3)
    p.lfo(1, 'sine', rate=0.15).mod('lfo1', 'flt1Cutoff', 0.12).mod('lfo1', 'op8Level', 0.3).mod('wheel', 'flt1Cutoff', 0.3)
    p.chorus(rate=0.3, depth=0.35, mix=0.35).reverb(size=0.8, decay=0.7, pre=20, mix=0.3)
    if extra: extra(p)
    return p
PADS = [
    ('Warm Pad', dict()),
    ('Glass Pad', dict(pm=0.2, ratio7=4, pm7=0.25, cutoff=5000, extra=lambda p: p.op(7, level=0.35, amp=adsr(1.5, 0.5, 0.8, 1.5)))),
    ('Dark Pad', dict(pm=0.35, fb=0.3, cutoff=900, attack=1.2, extra=lambda p: p.eq(low=2, lowf=120))),
    ('Evolving Pad', dict(pm=0.3, extra=lambda p: p.lfo(2, 'tri', rate=0.07).mod('lfo2', 'pm21', 0.2).mod('lfo2', 'op7Level', 0.3).lfo(3, 'sine', rate=0.11).mod('lfo3', 'op1Pan', 0.4).mod('lfo3', 'op3Pan', -0.4))),
    ('Choir Pad', dict(pm=0.25, cutoff=700, extra=lambda p: p.flt(1, 'BP', reso=0.5).out(1, f2=0.8).flt(2, 'BP', cutoff=1200, reso=0.5))),
    ('Strings Pad', dict(pm=0.42, fb=0.25, ratio7=3, pm7=0.1, cutoff=3500, attack=0.5)),
    ('Shimmer Pad', dict(pm=0.25, ratio7=2, pm7=0.3, cutoff=6000, extra=lambda p: p.reverb(size=0.98, decay=0.92, pre=40, mix=0.5).delay(div='1/4D', feedback=0.45, pingpong=True, tone=0.7, mix=0.25))),
    ('Drone', dict(pm=0.3, fb=0.5, unison=6, detune=6, attack=2.5, release=3, cutoff=1200, extra=lambda p: p.lfo(2, 'tri', rate=0.05).mod('lfo2', 'flt1Cutoff', 0.25).mod('lfo2', 'pm22', 0.2))),
    ('Dubstep Atmos', dict(pm=0.3, cutoff=1500, extra=lambda p: p.lfo(2, 'sine', div='1/2').mod('lfo2', 'flt1Cutoff', 0.2).lfo(3, 'sine', div='1/8').mod('lfo3', 'op1Level', -0.2).eq(low=2, lowf=80))),
    ('Cinematic Swell', dict(pm=0.4, unison=5, detune=10, attack=3.0, release=2.5, cutoff=2500, extra=lambda p: p.flt(1, cut=env([[0, 0], [3.5, 1, 0.3], [5, 1]], sustain=2), env=0.5).reverb(size=0.95, decay=0.85, mix=0.4))),
    ('Noise Wash', dict(pm=0.2, cutoff=1500, extra=lambda p: p.op(8, wave='noise', level=0.3, amp=adsr(1.5, 0.5, 0.8, 2.0)).out(8, dry=0, f2=1).flt(2, 'BP', cutoff=1800, reso=0.3).lfo(2, 'sine', rate=0.08).mod('lfo2', 'flt2Cutoff', 0.35))),
    ('Vocal Pad', dict(pm=0.3, cutoff=600, extra=lambda p: p.flt(1, 'BP', reso=0.55).out(1, f2=0.9).flt(2, 'BP', cutoff=1900, reso=0.5).lfo(2, 'sine', rate=0.2).mod('lfo2', 'flt1Cutoff', 0.25).mod('lfo2', 'flt2Cutoff', -0.2))),
    ('Sweep Pad', dict(pm=0.35, cutoff=800, extra=lambda p: p.lfo(2, 'tri', div='1/1').mod('lfo2', 'flt1Cutoff', 0.5).flt(1, reso=0.45))),
    ('Crystal Pad', dict(pm=0.15, ratio7=6, pm7=0.3, cutoff=9000, attack=0.4, extra=lambda p: p.op(7, amp=adsr(0.3, 1.5, 0.3, 1.5)).delay(div='1/8', feedback=0.4, pingpong=True, tone=0.8, mix=0.25))),
    ('Hollow Pad', dict(pm=0.0, cutoff=3000, extra=lambda p: p.op(1, partials=[1, 0, 0.33, 0, 0.2]).op(3, partials=[1, 0, 0.33, 0, 0.2]).op(2, level=0.0).op(4, level=0.0))),
    ('Brass Pad', dict(pm=0.45, fb=0.2, ratio7=2, pm7=0.2, cutoff=2800, attack=0.3, extra=lambda p: p.op(2, mod=swell(0.5, 0.3, 0.6)).op(4, mod=swell(0.5, 0.3, 0.6)))),
    ('Space Pad', dict(pm=0.25, ratio7=0.5, pm7=0.1, cutoff=2000, attack=1.5, extra=lambda p: p.phaser(rate=0.08, depth=0.8, stages=2, feedback=0.4, mix=0.4).reverb(size=0.95, decay=0.9, mix=0.45))),
    ('Fifths Pad', dict(pm=0.3, ratio7=1.5, pm7=0.0, cutoff=3000, extra=lambda p: p.op(7, level=0.7))),
    ('Ambient Bells Pad', dict(pm=0.2, ratio7=3.5, pm7=0.35, cutoff=7000, attack=0.6, extra=lambda p: p.op(7, amp=adsr(0.002, 3, 0.2, 2, t=-0.6), level=0.4).reverb(size=0.9, decay=0.85, mix=0.4))),
    ('Granular Shimmer', dict(pm=0.25, cutoff=4000, extra=lambda p: p.lfo(2, 'sh', div='1/16').mod('lfo2', 'op1Fine', 0.25).mod('lfo2', 'op1Pan', 0.6).mod('lfo2', 'op3Pan', -0.6).delay(div='1/16', feedback=0.6, pingpong=True, tone=0.7, mix=0.35))),
    ('Analog Poly Pad', dict(pm=0.4, fb=0.3, unison=3, detune=16, cutoff=2200, attack=0.3, release=0.8)),
    ('Ice Pad', dict(pm=0.15, ratio7=8, pm7=0.2, cutoff=12000, attack=1.0, extra=lambda p: p.eq(low=-6, lowf=200, high=3, highf=8000))),
    ('Underwater Pad', dict(pm=0.3, cutoff=500, attack=1.5, extra=lambda p: p.lfo(2, 'sine', rate=0.3).mod('lfo2', 'op1Fine', 0.15).mod('lfo2', 'flt1Cutoff', 0.2).phaser(rate=0.15, depth=0.6, mix=0.4))),
    ('Rotor Pad', dict(pm=0.3, cutoff=2500, extra=lambda p: p.lfo(2, 'sine', rate=1.5).mod('lfo2', 'op1Pan', 0.8).mod('lfo2', 'op3Pan', -0.8).mod('lfo2', 'op5Pan', 0.6))),
    ('Breath Pad', dict(pm=0.2, cutoff=1800, extra=lambda p: p.op(8, wave='noise', level=0.2, amp=adsr(1.0, 0.5, 0.8, 1.5)).out(8, dry=0, f2=1).flt(2, 'BP', cutoff=1200, reso=0.5).lfo(2, 'sine', rate=0.25).mod('lfo2', 'flt2Cutoff', 0.3).mod('lfo2', 'op8Level', 0.3))),
]
for nm, kw in PADS:
    base = pad(nm, **kw)
    variant(base, 'Slow', mod_slow)
    variant(base, 'Bright', mod_bright)
    variant(base, 'Dark', mod_dark)

# ----------------------------------------------------------------- PLUCKS ----
def pluck(name, pm=0.45, ratio2=1, decay=0.5, hold=0.0, ratio3=3, pm3=0.2, cutoff=5000, env_=0.4, delay=True, extra=None, cat=PLUCK):
    p = P(cat, name)
    p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.002, decay, hold, 0.15, t=-0.6))
    p.op(2, ratio=ratio2, level=0.8, vel=0.9, amp=perc(0.002, decay * 0.5)).pm(2, 1, pm)
    p.op(3, ratio=ratio3, level=0.4, vel=0.9, amp=perc(0.001, decay * 0.25)).pm(3, 1, pm3).pm(3, 4, pm3 * 0.5)
    p.op(4, ratio=2, level=0.5, vel=0.5, amp=adsr(0.002, decay * 0.8, hold, 0.15, t=-0.6)).op(5, ratio=ratio2 * 2, level=0.6, vel=0.9, amp=perc(0.002, decay * 0.4)).pm(5, 4, pm * 0.7)
    p.op(6, ratio=1, fine=6, level=0.5, amp=adsr(0.002, decay, hold, 0.15, t=-0.6)).op(7, ratio=5, level=0.3, vel=1, amp=perc(0.001, 0.06)).pm(7, 6, pm3).pm(7, 1, 0.1)
    p.op(8, wave='noise', level=0.15, amp=perc(0.001, 0.008))
    p.carriers(1, 4, 6, level=0.7, to='F1').out(8, dry=0.5).flt(1, 'LP', cutoff=cutoff, key=0.4, vel=0.3, env=env_, cut=perc(0.001, decay * 0.6))
    if delay: p.delay(div='1/8D', feedback=0.35, pingpong=True, tone=0.6, mix=0.22)
    p.reverb(size=0.5, decay=0.45, mix=0.18)
    if extra: extra(p)
    return p
PLUCKS = [
    ('FM Pluck', dict()),
    ('Trance Pluck', dict(pm=0.5, decay=0.35, cutoff=3000, env_=0.5, extra=lambda p: p.op(1, unison=3, detune=10, spread=0.8))),
    ('Dub Pluck', dict(pm=0.4, decay=0.3, cutoff=2000, extra=lambda p: p.delay(div='1/4D', feedback=0.55, pingpong=True, tone=0.35, mix=0.35))),
    ('Arp Saw', dict(pm=0.5, decay=0.25, hold=0.2, cutoff=4000, delay=False, extra=lambda p: p.fb(2, 0.3).delay(div='1/16', feedback=0.3, pingpong=True, tone=0.6, mix=0.2))),
    ('Arp Square', dict(pm=0.0, pm3=0.0, decay=0.25, hold=0.3, delay=False, extra=lambda p: p.op(1, partials=[1, 0, 0.33, 0, 0.2, 0, 0.14]).op(4, partials=[1, 0, 0.33]).delay(div='1/8', feedback=0.35, pingpong=True, mix=0.2))),
    ('Stab Pluck', dict(pm=0.55, pm3=0.3, decay=0.3, cutoff=6000)),
    ('Marimba Pluck', dict(pm=0.3, ratio2=4, decay=0.6, cutoff=8000, env_=0.0, delay=False)),
    ('Bell Pluck', dict(pm=0.35, ratio2=3.5, decay=1.5, ratio3=7, pm3=0.15, cutoff=9000, env_=0.0)),
    ('Pizzi Synth', dict(pm=0.4, pm3=0.15, decay=0.35, cutoff=3000)),
    ('Water Drop', dict(pm=0.3, ratio2=2, decay=0.5, cutoff=7000, env_=0.0, extra=lambda p: p.op(1, pitch=pitch_drop(0.0, 0.08, t=0.3), pitchamt=24).op(4, pitch=pitch_drop(0.0, 0.08, t=0.3), pitchamt=24))),
    ('Glass Pluck', dict(pm=0.25, ratio2=5, decay=1.2, cutoff=9000, env_=0.0, extra=lambda p: p.op(1, unison=2, detune=5, spread=0.9))),
    ('Gated Pluck', dict(pm=0.45, decay=1.5, hold=0.5, cutoff=4000, extra=lambda p: p.lfo(1, 'square', div='1/16').mod('lfo1', 'op1Level', -0.5).mod('lfo1', 'op4Level', -0.5))),
    ('Echo Pluck', dict(pm=0.45, decay=0.3, cutoff=4500, extra=lambda p: p.delay(div='1/8T', feedback=0.6, pingpong=True, tone=0.5, mix=0.4))),
    ('Harp Pluck', dict(pm=0.3, ratio2=2, decay=1.8, cutoff=6000, env_=0.2)),
    ('Kalimba Pluck', dict(pm=0.25, ratio2=2, decay=0.9, ratio3=9, pm3=0.1, cutoff=8000, env_=0.0)),
    ('Koto Pluck', dict(pm=0.5, ratio2=1, decay=1.0, ratio3=4, pm3=0.3, cutoff=5000, env_=0.3, extra=lambda p: p.op(1, pitch=pitch_drop(0.55, 0.06), pitchamt=4))),
    ('Steel Pluck', dict(pm=0.55, ratio2=1, decay=0.7, ratio3=7, pm3=0.25, cutoff=7000, env_=0.3)),
    ('Soft Pluck', dict(pm=0.25, decay=0.8, cutoff=2500, env_=0.2)),
    ('Chord Pluck', dict(pm=0.4, decay=0.6, cutoff=4000, extra=lambda p: p.op(6, ratio=1.5, fine=0, level=0.7).op(4, ratio=2, level=0.6))),
    ('Rhythm Arp', dict(pm=0.5, decay=0.2, hold=0.4, cutoff=3500, delay=False, extra=lambda p: p.lfo(1, 'square', div='1/16').mod('lfo1', 'flt1Cutoff', 0.3).delay(div='1/8D', feedback=0.3, pingpong=True, mix=0.2))),
]
for nm, kw in PLUCKS:
    base = pluck(nm, **kw)
    variant(base, 'Short', mod_short)
    variant(base, 'Long', mod_long)
    variant(base, 'Wide', mod_wide)

# ------------------------------------------------------- SYNTH KEYS / ORGANS -
p = P(EKEYS, 'FM E-Piano Deluxe')
p.op(1, ratio=1, level=1, vel=0.55, amp=adsr(0.002, 3.5, 0.0, 0.3, t=-0.6)).op(2, ratio=14, level=0.4, vel=0.95, amp=perc(0.002, 0.35)).pm(2, 1, 0.32)
p.op(3, ratio=1, level=0.8, vel=0.5, amp=adsr(0.002, 3.0, 0.0, 0.3, t=-0.6)).op(4, ratio=1, level=0.65, vel=0.85, amp=perc(0.002, 1.6)).pm(4, 3, 0.48)
p.op(5, ratio=1, fine=5, level=0.5, vel=0.5, amp=adsr(0.002, 2.5, 0.0, 0.3)).op(6, ratio=2, level=0.4, vel=0.9, amp=perc(0.002, 1.0)).pm(6, 5, 0.3).pm(6, 1, 0.1)
p.op(7, ratio=0.5, level=0.3, amp=adsr(0.004, 2.5, 0.0, 0.3)).op(8, ratio=7, level=0.3, vel=1, amp=perc(0.001, 0.3)).pm(8, 3, 0.15)
p.carriers(1, 3, 5, level=0.6).out(7, dry=0.5).lfo(1, 'sine', rate=4.8).mod('lfo1', 'op1Pan', 0.5).mod('lfo1', 'op3Pan', -0.5).chorus(rate=0.4, depth=0.25, mix=0.3).reverb(size=0.55, decay=0.45, mix=0.18)
variant(p, 'Hall', mod_hall); variant(p, 'Phased', lambda q: q.phaser(rate=0.3, depth=0.6, stages=1, mix=0.4))

DRAWBARS = {
    'Full': [(1, 0.9), (2, 0.8), (3, 0.6), (4, 0.5), (5, 0.3), (6, 0.35), (0.5, 0.6)],
    'Jazz': [(1, 0.8), (2, 0.4), (0.5, 0.6), (3, 0.2), (4, 0.1)],
    'Gospel': [(1, 0.9), (2, 0.7), (3, 0.5), (4, 0.4), (0.5, 0.5)],
    'Rock': [(1, 0.9), (2, 0.9), (0.5, 0.7), (3, 0.3), (4, 0.2)],
    'Flute': [(1, 0.9), (2, 0.2), (4, 0.1), (0.5, 0.3), (3, 0.08)],
    'Reggae': [(1, 0.8), (2, 0.6), (0.5, 0.4), (3, 0.3), (4, 0.2)],
    'Theatre': [(1, 0.8), (2, 0.5), (3, 0.4), (4, 0.3), (6, 0.3), (8, 0.2), (0.5, 0.4)],
    'Cheese': [(1, 0.7), (2, 0.7), (3, 0.6), (4, 0.6), (5, 0.5), (6, 0.5), (8, 0.4)],
}
for nm, bars in DRAWBARS.items():
    organ8('%s Organ' % nm, bars, perc_=0.3 if nm in ('Jazz', 'Gospel', 'Rock') else 0.0, drive=0.3 if nm in ('Rock', 'Gospel') else 0.0, leslie=6.0, cat=EKEYS)
    organ8('%s Organ Slow Leslie' % nm, bars, perc_=0.3 if nm in ('Jazz', 'Gospel', 'Rock') else 0.0, drive=0.3 if nm in ('Rock', 'Gospel') else 0.0, leslie=0.8, cat=EKEYS)
organ8('House Organ', [(1, 0.9), (2, 0.8), (3, 0.6), (4, 0.5), (0.5, 0.6)], perc_=0.4, drive=0.2, cat=EKEYS).chorus(rate=0.8, depth=0.3, mix=0.3)
organ8('Dirty Organ', [(1, 0.9), (2, 0.7), (3, 0.5), (4, 0.4), (0.5, 0.5)], perc_=0.3, drive=0.55, leslie=6.0, cat=EKEYS)
organ8('Farfisa', [(1, 0.8), (2, 0.6), (4, 0.4), (8, 0.3), (3, 0.3)], click=0.2, cat=EKEYS).op(1, partials=[1, 0, 0.3, 0, 0.2]).lfo(2, 'sine', rate=5.5).mod('lfo2', 'op1Fine', 0.05)

def synkeys(name, fn, cat=EKEYS):
    p = P(cat, name)
    fn(p)
    return p
synkeys('Synth Clav', lambda p: p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.001, 1.2, 0.0, 0.08, t=-0.6)).op(2, ratio=1, level=0.85, vel=0.9, amp=perc(0.001, 0.3)).pm(2, 1, 0.55).fb(2, 0.3)
    .op(3, ratio=2, level=0.6, amp=adsr(0.001, 1.0, 0.0, 0.08, t=-0.6)).op(4, ratio=3, level=0.6, amp=perc(0.001, 0.25)).pm(4, 3, 0.4).op(5, ratio=5, level=0.3, amp=perc(0.001, 0.05)).pm(5, 1, 0.2).pm(5, 3, 0.2)
    .op(6, ratio=1, level=0.4, amp=perc(0.001, 0.3)).fb(6, 0.5).rm(6, 1, 0.2).op(7, ratio=0.5, level=0.4, amp=adsr(0.001, 0.9, 0.0, 0.08)).op(8, wave='noise', level=0.2, amp=perc(0.001, 0.01))
    .carriers(1, 3, to='F1').out(7, dry=0.5).out(8, f2=0.6).flt(1, 'LP', cutoff=1500, reso=0.5, env=0.5, vel=0.3, cut=perc(0.001, 0.2)).flt(2, 'HP', cutoff=3000)
    .phaser(rate=0.4, depth=0.6, stages=1, feedback=0.3, mix=0.35).comp(thresh=-16, ratio=4, attack=3))
synkeys('Bell Keys', lambda p: p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.002, 2.5, 0.1, 0.6, t=-0.6)).op(2, ratio=3.5, level=0.5, vel=0.9, amp=perc(0.002, 1.2)).pm(2, 1, 0.35)
    .op(3, ratio=1, fine=5, level=0.6, amp=adsr(0.002, 2.0, 0.1, 0.6, t=-0.6)).op(4, ratio=7, level=0.3, amp=perc(0.002, 0.4)).pm(4, 3, 0.2).op(5, ratio=2, level=0.5, amp=adsr(0.002, 1.8, 0.1, 0.6, t=-0.6)).op(6, ratio=5, level=0.3, amp=perc(0.002, 0.6)).pm(6, 5, 0.25)
    .op(7, ratio=0.5, level=0.3, amp=adsr(0.002, 2.0, 0.1, 0.6)).op(8, ratio=11, level=0.25, amp=perc(0.002, 0.3)).pm(8, 1, 0.1).pm(8, 5, 0.1)
    .carriers(1, 3, 5, level=0.7).out(7, dry=0.5).chorus(rate=0.3, depth=0.25, mix=0.3).reverb(size=0.7, decay=0.6, mix=0.3))
synkeys('Glass Keys', lambda p: p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.005, 1.8, 0.2, 0.5, t=-0.6)).op(2, ratio=4, level=0.45, vel=0.9, amp=perc(0.005, 0.8)).pm(2, 1, 0.28)
    .op(3, ratio=2, level=0.5, vel=0.6, amp=adsr(0.005, 1.5, 0.2, 0.5)).op(4, ratio=6, level=0.35, amp=perc(0.005, 0.5)).pm(4, 3, 0.25).op(5, ratio=1, fine=-6, level=0.5, amp=adsr(0.005, 1.6, 0.2, 0.5)).op(6, ratio=9, level=0.25, amp=perc(0.005, 0.4)).pm(6, 5, 0.18)
    .op(7, ratio=3, level=0.3, amp=adsr(0.005, 1.2, 0.2, 0.5)).op(8, ratio=0.5, level=0.3, amp=adsr(0.005, 1.5, 0.2, 0.5))
    .carriers(1, 3, 5, 7, level=0.6).out(8, dry=0.5).delay(div='1/8D', feedback=0.3, pingpong=True, tone=0.7, mix=0.2).reverb(size=0.65, decay=0.55, mix=0.25))
synkeys('Lo-fi Keys', lambda p: p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.003, 2.0, 0.1, 0.3, t=-0.6)).op(2, ratio=1, level=0.6, vel=0.8, amp=perc(0.003, 1.0)).pm(2, 1, 0.4)
    .op(3, ratio=2, level=0.5, amp=adsr(0.003, 1.8, 0.1, 0.3, t=-0.6)).op(4, ratio=3, level=0.4, amp=perc(0.003, 0.6)).pm(4, 3, 0.3).op(5, ratio=1, fine=9, level=0.5, amp=adsr(0.003, 2.0, 0.1, 0.3, t=-0.6)).op(6, ratio=1, level=0.4, amp=perc(0.003, 0.8)).pm(6, 5, 0.35)
    .op(7, ratio=0.5, level=0.3, amp=adsr(0.003, 1.6, 0.1, 0.3)).op(8, wave='noise', level=0.06, amp=adsr(0.01, 0.5, 0.3, 0.3))
    .carriers(1, 3, 5, level=0.6, to='F1').out(7, dry=0.5).out(8, dry=0.5).flt(1, 'LP', cutoff=2200, key=0.3).lfo(1, 'sine', rate=0.7).mod('lfo1', 'op1Fine', 0.06).mod('lfo1', 'op5Fine', -0.06)
    .dist('crush', drive=0.25, tone=0.55, mix=0.5).chorus(rate=0.2, depth=0.3, mix=0.3).reverb(size=0.5, decay=0.5, mix=0.2))
synkeys('Dream Keys', lambda p: p.op(1, ratio=1, level=1, unison=2, detune=6, spread=0.8, vel=0.5, amp=adsr(0.01, 2.5, 0.3, 1.0, t=-0.6)).op(2, ratio=2, level=0.5, vel=0.8, amp=perc(0.01, 1.5)).pm(2, 1, 0.3)
    .op(3, ratio=1, level=0.6, vel=0.4, amp=adsr(0.3, 1.0, 0.6, 1.2)).op(4, ratio=3, level=0.4, amp=adsr(0.3, 1.0, 0.5, 1.2)).pm(4, 3, 0.25).op(5, ratio=2, fine=5, level=0.4, amp=adsr(0.01, 2.0, 0.3, 1.0)).op(6, ratio=4, level=0.3, amp=perc(0.01, 1.0)).pm(6, 5, 0.2)
    .op(7, ratio=0.5, level=0.35, amp=adsr(0.02, 2.0, 0.4, 1.0)).op(8, ratio=8, level=0.2, amp=perc(0.01, 0.6)).pm(8, 1, 0.08)
    .carriers(1, 3, 5, level=0.6).out(7, dry=0.5).delay(div='1/4D', feedback=0.4, pingpong=True, tone=0.6, mix=0.25).reverb(size=0.9, decay=0.8, mix=0.4))
synkeys('80s FM Keys', lambda p: p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.002, 1.5, 0.3, 0.3, t=-0.6)).op(2, ratio=3, level=0.6, vel=0.9, amp=perc(0.002, 0.6)).pm(2, 1, 0.4)
    .op(3, ratio=1, fine=-6, level=0.7, amp=adsr(0.002, 1.5, 0.3, 0.3, t=-0.6)).op(4, ratio=5, level=0.3, amp=perc(0.002, 0.3)).pm(4, 3, 0.25).op(5, ratio=2, level=0.5, amp=adsr(0.002, 1.2, 0.3, 0.3)).op(6, ratio=14, level=0.25, amp=perc(0.002, 0.2)).pm(6, 5, 0.2)
    .op(7, ratio=0.5, level=0.3, amp=adsr(0.002, 1.5, 0.3, 0.3)).op(8, ratio=1, level=0.5, amp=perc(0.002, 0.8)).pm(8, 1, 0.2).fb(8, 0.3)
    .carriers(1, 3, 5, level=0.6).out(7, dry=0.5).chorus(rate=0.9, depth=0.4, mix=0.4).reverb(size=0.6, decay=0.5, mix=0.22))
synkeys('Wurly Dirty', lambda p: (None, p.op(1, ratio=1, level=1, vel=0.55, amp=adsr(0.002, 3.0, 0.0, 0.3, t=-0.6)).op(2, ratio=1, level=0.7, vel=0.9, amp=perc(0.002, 1.2)).pm(2, 1, 0.5)
    .op(3, ratio=2, level=0.5, amp=adsr(0.002, 2.5, 0.0, 0.3, t=-0.6)).op(4, ratio=1, level=0.6, amp=perc(0.002, 0.8)).pm(4, 3, 0.4).op(5, ratio=7, level=0.3, amp=perc(0.002, 0.3)).pm(5, 1, 0.2)
    .op(6, ratio=1, level=0.4, amp=perc(0.002, 0.5)).fb(6, 0.4).pm(6, 2, 0.2).op(7, ratio=0.5, level=0.3, amp=adsr(0.002, 2.0, 0.0, 0.3)).op(8, wave='noise', level=0.1, amp=perc(0.001, 0.02))
    .carriers(1, 3, level=0.7).out(7, dry=0.5).out(8, dry=0.3).lfo(1, 'sine', rate=5.5).mod('lfo1', 'op1Level', -0.3).mod('lfo1', 'op3Level', -0.3).dist('soft', drive=0.5, tone=0.6, mix=0.7).eq(mid=2, midf=1200).reverb(size=0.5, decay=0.4, mix=0.15)))
synkeys('Clavi Funk', lambda p: p.op(1, ratio=1, level=1, vel=0.6, amp=adsr(0.001, 0.8, 0.0, 0.06, t=-0.6)).op(2, ratio=1, level=0.9, vel=1.0, amp=perc(0.001, 0.2)).pm(2, 1, 0.6).fb(2, 0.35)
    .op(3, ratio=2, level=0.5, amp=adsr(0.001, 0.7, 0.0, 0.06, t=-0.6)).op(4, ratio=2, level=0.7, amp=perc(0.001, 0.15)).pm(4, 3, 0.5).op(5, ratio=7, level=0.3, amp=perc(0.001, 0.04)).pm(5, 1, 0.25)
    .op(6, ratio=3, level=0.4, amp=perc(0.001, 0.2)).rm(6, 1, 0.25).op(7, ratio=0.5, level=0.3, amp=adsr(0.001, 0.6, 0.0, 0.06)).op(8, wave='noise', level=0.25, amp=perc(0.001, 0.008))
    .carriers(1, 3, to='F1').out(7, dry=0.4).out(8, dry=0.4).flt(1, 'LP', cutoff=2500, reso=0.55, env=0.5, vel=0.4, cut=perc(0.001, 0.15)).mod('wheel', 'flt1Cutoff', 0.4).comp(thresh=-16, ratio=4, attack=2))
for nm in ('Bell Keys', 'Glass Keys', 'Dream Keys', '80s FM Keys', 'Synth Clav'):
    variant(next(x for x in PRESETS if x.name == nm), 'Echo', mod_echo)
    variant(next(x for x in PRESETS if x.name == nm), 'Dark', mod_dark)

# ---------------------------------------------------------- CHORDS / STABS ----
# stab: root (1 <- 2 feedback), fifth (3 <- 4), octave (5 <- 6), shared bright modulator (7) into 1/3/5, sub (8)
def stab(name, pm=0.5, fb=0.25, fifth=0.8, octave=0.5, unison=3, detune=12, decay=0.4, hold=0.0, cutoff=3500, drive=0.0, extra=None, cat=STAB):
    p = P(cat, name)
    a = adsr(0.004, decay, hold, 0.2, t=-0.5)
    p.op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.8, vel=0.4, amp=a).op(2, ratio=1, level=0.85, vel=0.6, amp=a).pm(2, 1, pm).fb(2, fb)
    p.op(3, ratio=1.5, level=fifth, unison=2, detune=8, spread=0.8, amp=a).op(4, ratio=1.5, level=0.7, amp=a).pm(4, 3, pm * 0.7)
    p.op(5, ratio=2, level=octave, amp=a).op(6, ratio=2, level=0.6, amp=a).pm(6, 5, pm * 0.6)
    p.op(7, ratio=3, level=0.4, vel=0.8, amp=perc(0.002, decay * 0.5)).pm(7, 1, 0.2).pm(7, 3, 0.15).pm(7, 5, 0.15)
    p.op(8, ratio=0.5, level=0.4, amp=a)
    p.carriers(1, 3, 5, to='F1').out(8, dry=0.5).flt(1, 'LP', cutoff=cutoff, key=0.3, vel=0.3, env=0.3, cut=perc(0.002, decay))
    if drive: p.dist('soft', drive=drive, mix=0.5)
    p.delay(div='1/8D', feedback=0.3, pingpong=True, tone=0.5, mix=0.2).reverb(size=0.6, decay=0.5, mix=0.2).comp(thresh=-14, ratio=3, attack=5)
    if extra: extra(p)
    return p
STABS = [
    ('House Stab', dict()), ('Rave Stab', dict(fifth=0.9, octave=0.6, pm=0.55, fb=0.35, unison=5, detune=18, cutoff=5000, drive=0.3)),
    ('Power Chord', dict(fifth=1.0, octave=0.7, pm=0.5, decay=1.0, hold=0.6, cutoff=3000, drive=0.4)),
    ('Piano Stab', dict(pm=0.42, unison=1, fifth=0.0, octave=0.6, decay=0.8, cutoff=6000)),
    ('Organ Stab', dict(pm=0.0, fifth=0.6, octave=0.8, unison=1, decay=0.2, hold=1.0, cutoff=8000, extra=lambda p: p.op(2, level=0.0).op(4, level=0.0).op(6, level=0.0))),
    ('Brass Stab', dict(pm=0.5, fb=0.2, fifth=0.5, decay=0.5, hold=0.3, cutoff=3000, extra=lambda p: p.op(2, mod=swell(0.08, 0.3, 0.6)))),
    ('Detuned Stab', dict(fifth=0.7, unison=6, detune=24, pm=0.45, cutoff=4000)),
    ('Dub Chord', dict(fifth=0.7, octave=0.3, pm=0.35, decay=0.3, cutoff=1800, extra=lambda p: p.delay(div='1/4D', feedback=0.6, pingpong=True, tone=0.3, mix=0.45))),
    ('Garage Chord', dict(fifth=0.6, octave=0.5, pm=0.45, decay=0.25, cutoff=4000, extra=lambda p: p.flt(1, reso=0.4))),
    ('Dubstep Chord Stab', dict(fifth=0.9, octave=0.5, pm=0.5, fb=0.35, unison=4, detune=16, decay=0.6, hold=0.5, cutoff=1200, drive=0.4, extra=lambda p: p.lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.35))),
    ('Trap Chord', dict(fifth=0.7, octave=0.4, pm=0.3, decay=1.2, hold=0.4, cutoff=2500, extra=lambda p: p.op(1, amp=adsr(0.02, 1.2, 0.4, 0.4)).chorus(rate=0.3, depth=0.3, mix=0.3))),
    ('Techno Stab', dict(fifth=0.8, octave=0.6, pm=0.5, fb=0.3, decay=0.2, cutoff=2500, drive=0.3, extra=lambda p: p.flt(1, reso=0.5))),
    ('Lo-fi Chord', dict(fifth=0.6, octave=0.5, pm=0.35, decay=0.9, hold=0.3, cutoff=2000, extra=lambda p: p.dist('crush', drive=0.3, tone=0.5, mix=0.5))),
    ('Octave Stab', dict(fifth=0.0, octave=0.9, pm=0.5, unison=4, detune=14, decay=0.35, cutoff=4500)),
    ('Sus Chord', dict(fifth=0.8, octave=0.5, pm=0.4, decay=1.5, hold=0.7, cutoff=3000, extra=lambda p: p.op(5, ratio=4, level=0.3))),
]
for nm, kw in STABS:
    base = stab(nm, **kw)
    variant(base, 'Wide', mod_wide)
    variant(base, 'Short', mod_short)
    variant(base, 'Echo', mod_echo)

# --------------------------------------------------------- DRUMS / PERCUSSION -
def drum(name, extra, cat=DRUM):
    p = P(cat, name)
    p.poly(8).p['bendRange'] = 0
    extra(p)
    return p
# kick: body (1 pitch-dropping), a 2nd harmonic body (2 <- 1 PM for the knock), click (3 <- 4), noise (5)
def kick(name, hz=50, decay=0.9, drop=36, punch=0.4, click=0.3, drive=0.3, dtype='soft'):
    return drum(name, lambda p: p.op(1, ratio=1, level=1, amp=perc(0.001, decay, t=-0.5), pitch=pitch_drop(0.9, 0.05), pitchamt=drop, fixed=True, hz=hz)
         .op(2, ratio=1, level=0.6, amp=perc(0.001, 0.08), fixed=True, hz=hz * 2, pitch=pitch_drop(0.9, 0.03), pitchamt=drop).pm(2, 1, punch)
         .op(3, ratio=1, level=0.5, amp=perc(0.001, 0.02), fixed=True, hz=1200).op(4, ratio=1, level=0.6, amp=perc(0.001, 0.01), fixed=True, hz=4000).pm(4, 3, 0.5)
         .op(5, wave='noise', level=click, amp=perc(0.001, 0.012)).carriers(1, 3, 5)
         .dist(dtype, drive=drive, tone=0.45, mix=0.5).eq(low=2.5, lowf=60, lowcut=25, mid=2, midf=3000).comp(thresh=-10, ratio=5, attack=4, limit=True))
for hz, tn in ((42, 'Deep'), (48, 'Low'), (55, 'Mid'), (62, 'High')):
    kick('Kick 808 %s' % tn, hz=hz, decay=1.2, drop=36, punch=0.3, click=0.15)
    kick('Kick Punch %s' % tn, hz=hz, decay=0.35, drop=48, punch=0.5, click=0.4, dtype='hard', drive=0.4)
    kick('Kick Dubstep %s' % tn, hz=hz, decay=0.6, drop=40, punch=0.45, click=0.35, drive=0.5)
    kick('Kick Techno %s' % tn, hz=hz, decay=0.45, drop=30, punch=0.35, click=0.25, drive=0.45, dtype='hard')
kick('Kick Trap Boom', hz=45, decay=2.2, drop=36, punch=0.25, click=0.1)
kick('Kick Tight', hz=58, decay=0.2, drop=48, punch=0.5, click=0.5, dtype='hard', drive=0.3)

def snare(name, hz=185, decay=0.2, noise=0.7, tone=0.5, hp=1200, drive=0.3, pm=0.5):
    return drum(name, lambda p: p.op(1, ratio=1, level=1, amp=perc(0.001, decay), pitch=pitch_drop(0.8, 0.03), pitchamt=24, fixed=True, hz=hz).op(2, ratio=1, level=0.7, amp=perc(0.001, 0.08), fixed=True, hz=hz * 1.6).pm(2, 1, pm)
         .op(3, wave='noise', level=noise, amp=perc(0.001, decay * 1.1)).op(4, wave='noise', level=noise * 0.6, amp=perc(0.001, 0.04)).op(5, ratio=1, level=tone, fixed=True, hz=hz * 2.4, amp=perc(0.001, 0.1)).op(6, ratio=1, level=0.4, fixed=True, hz=hz * 3.7, amp=perc(0.001, 0.06)).pm(6, 5, 0.4)
         .carriers(1, 5).out(3, f1=1).out(4, f2=1).flt(1, 'HP', cutoff=hp, reso=0.2).flt(2, 'BP', cutoff=4000, reso=0.4)
         .dist('soft', drive=drive, mix=0.4).eq(mid=3, midf=hz * 1.1, q=1.5, high=2, highf=6000).comp(thresh=-12, ratio=4, attack=2).reverb(size=0.3, decay=0.25, mix=0.1))
snare('Snare FM'); snare('Snare Tight', decay=0.12, noise=0.6, hp=1500); snare('Snare Fat', hz=160, decay=0.3, noise=0.8, tone=0.6, hp=800)
snare('Snare Dubstep', hz=200, decay=0.25, noise=0.9, tone=0.7, hp=1000, drive=0.5); snare('Snare Trap', hz=220, decay=0.15, noise=0.7, hp=1800, drive=0.2)
snare('Snare Noise', hz=200, decay=0.25, noise=1.0, tone=0.2, hp=2000, pm=0.2); snare('Snare Rim Tone', hz=240, decay=0.1, noise=0.4, tone=0.8, hp=2500, pm=0.6)
snare('Snare Big Room', hz=170, decay=0.35, noise=0.9, tone=0.6, hp=900, drive=0.4).reverb(size=0.7, decay=0.6, mix=0.3)

def clap(name, spread=0.012, tail=0.35, hz=1500, verb=0.2):
    pts = [[0, 1], [spread, 0.3, -0.5], [spread + 0.002, 1], [2 * spread + 0.002, 0.3, -0.5], [2 * spread + 0.004, 1], [3 * spread + 0.004, 0.25, -0.5], [3 * spread + 0.006, 0.9], [tail, 0, -0.6]]
    return drum(name, lambda p: p.op(1, wave='noise', level=1, amp=env(pts, sustain=-1)).op(2, wave='noise', level=1, amp=env(pts, sustain=-1)).op(3, wave='noise', level=0.6, amp=perc(0.001, tail * 1.5, t=-0.4))
         .op(4, ratio=1, level=0.3, fixed=True, hz=hz * 0.6, amp=perc(0.001, 0.03)).carriers(1, 2, 4, to='F1').out(1, dry=0.4).out(3, f2=1).flt(1, 'BP', cutoff=hz, reso=0.35, slope=12).flt(2, 'BP', cutoff=hz * 1.4, reso=0.3)
         .dist('soft', drive=0.3, mix=0.5).reverb(size=0.4, decay=0.35, mix=verb).eq(high=2, highf=5000).comp(thresh=-12, ratio=4, attack=1))
clap('Clap'); clap('Clap Tight', spread=0.008, tail=0.2, verb=0.1); clap('Clap Big', spread=0.015, tail=0.6, hz=1200, verb=0.35); clap('Clap Bright', hz=2200)

def hat(name, decay=0.05, open_=False, hz1=6300, hz2=9100, hp=6000):
    d = 0.45 if open_ else decay
    return drum(name, lambda p: p.op(1, wave='noise', level=1, amp=perc(0.001, d, t=-0.4 if open_ else -0.6)).op(2, ratio=1, level=0.8, fixed=True, hz=hz1, amp=perc(0.001, d * 0.8)).op(3, ratio=1, level=0.8, fixed=True, hz=hz2, amp=perc(0.001, d * 0.8)).rm(2, 3, 0.8)
         .op(4, wave='noise', level=1, amp=perc(0.001, d)).op(5, ratio=1, level=0.6, fixed=True, hz=hz1 * 1.37, amp=perc(0.001, d * 0.7)).op(6, ratio=1, level=0.6, fixed=True, hz=hz2 * 1.21, amp=perc(0.001, d * 0.7)).rm(5, 6, 0.8).rm(6, 3, 0.3)
         .carriers(1, 3, 4, 6, to='F1').out(1, dry=0.5).flt(1, 'HP', cutoff=hp, reso=0.2).eq(high=3, highf=10000).comp(thresh=-14, ratio=4, attack=1))
hat('Hi-Hat Closed'); hat('Hi-Hat Open', open_=True); hat('Hi-Hat Pedal', decay=0.08, hp=4500); hat('Hi-Hat Tight', decay=0.03, hp=7500)
hat('Hi-Hat Dark', decay=0.06, hz1=4200, hz2=6100, hp=4000); hat('Hi-Hat Open Long', open_=True, hz1=5800, hz2=8400, hp=5000)
hat('Hi-Hat Trap', decay=0.04, hz1=7000, hz2=10000, hp=8000); hat('Hi-Hat 808', decay=0.05, hz1=5400, hz2=8900, hp=5500)

def tom(name, hz=130, decay=0.5, drop=12):
    return drum(name, lambda p: p.op(1, ratio=1, level=1, amp=perc(0.001, decay), pitch=pitch_drop(0.8, 0.08), pitchamt=drop, fixed=True, hz=hz).op(2, ratio=1, level=0.5, amp=perc(0.001, 0.15), fixed=True, hz=hz * 1.5).pm(2, 1, 0.35)
         .op(3, ratio=1, level=0.4, amp=perc(0.001, decay * 0.6), fixed=True, hz=hz * 2.3).op(4, ratio=1, level=0.5, amp=perc(0.001, 0.1), fixed=True, hz=hz * 3.4).pm(4, 3, 0.3)
         .op(5, wave='noise', level=0.15, amp=perc(0.001, 0.03)).carriers(1, 3, 5).eq(low=2, lowf=hz).comp(thresh=-12, ratio=4, attack=3).reverb(size=0.4, decay=0.3, mix=0.12))
tom('Tom Floor', hz=80, decay=0.7); tom('Tom Low', hz=110, decay=0.6); tom('Tom Mid', hz=150, decay=0.5); tom('Tom High', hz=200, decay=0.4)
tom('Tom 808 Low', hz=90, decay=0.9, drop=18); tom('Tom 808 High', hz=170, decay=0.7, drop=18); tom('Roto Tom', hz=250, decay=0.5, drop=30)


def hit(name, fn):
    return drum(name, fn)
hit('Rimshot', lambda p: p.op(1, ratio=1, level=1, fixed=True, hz=450, amp=perc(0.001, 0.06)).op(2, ratio=1, level=0.8, fixed=True, hz=1700, amp=perc(0.001, 0.03)).pm(2, 1, 0.6).op(3, wave='noise', level=0.6, amp=perc(0.001, 0.015))
    .op(4, ratio=1, level=1, fixed=True, hz=900, amp=perc(0.001, 0.05)).op(5, ratio=1, level=0.6, fixed=True, hz=2600, amp=perc(0.001, 0.02)).pm(5, 4, 0.5).carriers(1, 3, 4).dist('soft', drive=0.3, mix=0.5).eq(mid=4, midf=2000, q=1.5).comp(thresh=-12, ratio=4, attack=1))
hit('Sidestick', lambda p: p.op(1, ratio=1, level=1, fixed=True, hz=380, amp=perc(0.001, 0.04)).op(2, ratio=1, level=0.7, fixed=True, hz=2200, amp=perc(0.001, 0.02)).pm(2, 1, 0.5).op(3, wave='noise', level=0.5, amp=perc(0.001, 0.01))
    .carriers(1, 3).eq(mid=3, midf=1500, q=1.5).comp(thresh=-12, ratio=4, attack=1))
for nm, (h1, h2) in (('Cowbell 808', (540, 800)), ('Cowbell Low', (400, 590)), ('Cowbell High', (720, 1060))):
    hit(nm, lambda p, h1=h1, h2=h2: p.op(1, partials=[1, 0, 0.3], level=0.8, fixed=True, hz=h1, amp=perc(0.001, 0.3)).op(2, partials=[1, 0, 0.3], level=0.8, fixed=True, hz=h2, amp=perc(0.001, 0.3))
        .op(3, ratio=1, level=0.5, fixed=True, hz=h1 * 2.9, amp=perc(0.001, 0.15)).op(4, ratio=1, level=0.5, fixed=True, hz=h2 * 2.6, amp=perc(0.001, 0.1)).pm(4, 3, 0.3).rm(3, 1, 0.2)
        .carriers(1, 2, 3, to='F1').flt(1, 'BP', cutoff=1800, reso=0.3, slope=12).comp(thresh=-12, ratio=4, attack=1))
def cymbal(name, decay=1.8, hz1=5300, hz2=7900, hp=3500, verb=0.2):
    return hit(name, lambda p: p.op(1, wave='noise', level=1, amp=perc(0.001, decay, t=-0.3)).op(2, ratio=1, level=0.6, fixed=True, hz=hz1, amp=perc(0.001, decay * 0.8)).op(3, ratio=1, level=0.6, fixed=True, hz=hz2, amp=perc(0.001, decay * 0.8)).rm(2, 3, 0.8).pm(3, 2, 0.4)
        .op(4, ratio=1, level=0.5, fixed=True, hz=hz1 * 1.43, amp=perc(0.001, decay * 0.9)).op(5, ratio=1, level=0.5, fixed=True, hz=hz2 * 1.19, amp=perc(0.001, decay * 0.9)).rm(4, 5, 0.8).pm(5, 4, 0.3).rm(5, 3, 0.3)
        .op(6, wave='noise', level=0.6, amp=perc(0.001, decay * 0.5)).carriers(1, 2, 4, 6, to='F1').flt(1, 'HP', cutoff=hp, reso=0.2).reverb(size=0.5, decay=0.5, mix=verb).comp(thresh=-14, ratio=4, attack=1))
cymbal('Cymbal Crash'); cymbal('Cymbal Crash Long', decay=3.0, verb=0.3); cymbal('Cymbal Ride', decay=1.2, hz1=4100, hz2=6300, hp=3000)
cymbal('Cymbal Ride Bell', decay=0.9, hz1=3100, hz2=4700, hp=2500); cymbal('Cymbal Splash', decay=0.6, hz1=6900, hz2=9800, hp=5000); cymbal('Cymbal China', decay=1.4, hz1=3600, hz2=5200, hp=2800)
def shaker(name, decay=0.06, hp=7000, attack=0.001):
    return hit(name, lambda p: p.op(1, wave='noise', level=1, amp=env([[0, 0], [attack, 1], [attack + decay, 0, -0.5]], sustain=-1)).op(2, wave='noise', level=0.7, amp=perc(0.001, decay * 0.5))
        .op(3, ratio=1, level=0.4, fixed=True, hz=8200, amp=perc(0.001, decay * 0.4)).op(4, ratio=1, level=0.5, fixed=True, hz=11700, amp=perc(0.001, decay * 0.3)).rm(3, 4, 0.8).carriers(1, 2, 3, to='F1').flt(1, 'HP', cutoff=hp, reso=0.3).comp(thresh=-14, ratio=4, attack=1))
shaker('Shaker'); shaker('Shaker Soft', decay=0.09, attack=0.015, hp=6000); shaker('Maracas', decay=0.05, hp=5500); shaker('Cabasa', decay=0.12, attack=0.02, hp=4500)
hit('Tambourine', lambda p: p.op(1, wave='noise', level=0.8, amp=perc(0.001, 0.12)).op(2, ratio=1, level=0.6, fixed=True, hz=7200, amp=perc(0.001, 0.15)).op(3, ratio=1, level=0.6, fixed=True, hz=9800, amp=perc(0.001, 0.15)).rm(2, 3, 0.7)
    .op(4, ratio=1, level=0.5, fixed=True, hz=5600, amp=perc(0.001, 0.2)).op(5, ratio=1, level=0.5, fixed=True, hz=11300, amp=perc(0.001, 0.12)).rm(4, 5, 0.7)
    .carriers(1, 2, 4, to='F1').flt(1, 'HP', cutoff=5000).comp(thresh=-14, ratio=4, attack=1))
hit('Wood Block', lambda p: p.op(1, ratio=1, level=1, fixed=True, hz=820, amp=perc(0.001, 0.05)).op(2, ratio=1, level=0.7, fixed=True, hz=2460, amp=perc(0.001, 0.02)).pm(2, 1, 0.4).op(3, wave='noise', level=0.3, amp=perc(0.001, 0.005))
    .carriers(1, 3).eq(mid=3, midf=1800, q=1.5).comp(thresh=-12, ratio=4, attack=1))
hit('Clave', lambda p: p.op(1, ratio=1, level=1, fixed=True, hz=2500, amp=perc(0.001, 0.04)).op(2, ratio=1, level=0.5, fixed=True, hz=4100, amp=perc(0.001, 0.02)).pm(2, 1, 0.3).op(3, wave='noise', level=0.2, amp=perc(0.001, 0.004)).carriers(1, 3).comp(thresh=-12, ratio=4, attack=1))
hit('Conga Low', lambda p: p.op(1, ratio=1, level=1, fixed=True, hz=190, amp=perc(0.001, 0.3), pitch=pitch_drop(0.7, 0.03), pitchamt=12).op(2, ratio=1, level=0.6, fixed=True, hz=380, amp=perc(0.001, 0.08)).pm(2, 1, 0.4).op(3, wave='noise', level=0.2, amp=perc(0.001, 0.01))
    .carriers(1, 3).eq(mid=2, midf=400).comp(thresh=-12, ratio=4, attack=2))
hit('Conga High', lambda p: p.op(1, ratio=1, level=1, fixed=True, hz=260, amp=perc(0.001, 0.25), pitch=pitch_drop(0.7, 0.03), pitchamt=12).op(2, ratio=1, level=0.6, fixed=True, hz=520, amp=perc(0.001, 0.08)).pm(2, 1, 0.4).op(3, wave='noise', level=0.25, amp=perc(0.001, 0.01))
    .carriers(1, 3).eq(mid=2, midf=600).comp(thresh=-12, ratio=4, attack=2))
hit('Conga Slap', lambda p: p.op(1, ratio=1, level=1, fixed=True, hz=300, amp=perc(0.001, 0.12), pitch=pitch_drop(0.9, 0.02), pitchamt=24).op(2, ratio=1, level=0.8, fixed=True, hz=900, amp=perc(0.001, 0.05)).pm(2, 1, 0.6).op(3, wave='noise', level=0.5, amp=perc(0.001, 0.02))
    .carriers(1, 3).dist('soft', drive=0.3, mix=0.4).eq(mid=3, midf=1500).comp(thresh=-12, ratio=4, attack=1))
hit('Bongo', lambda p: p.op(1, ratio=1, level=1, fixed=True, hz=420, amp=perc(0.001, 0.15), pitch=pitch_drop(0.7, 0.02), pitchamt=12).op(2, ratio=1, level=0.6, fixed=True, hz=1300, amp=perc(0.001, 0.04)).pm(2, 1, 0.45).op(3, wave='noise', level=0.2, amp=perc(0.001, 0.008))
    .carriers(1, 3).comp(thresh=-12, ratio=4, attack=1))
hit('Timbale', lambda p: p.op(1, ratio=1, level=1, fixed=True, hz=330, amp=perc(0.001, 0.4), pitch=pitch_drop(0.7, 0.04), pitchamt=12).op(2, ratio=1, level=0.7, fixed=True, hz=990, amp=perc(0.001, 0.1)).pm(2, 1, 0.5).op(3, wave='noise', level=0.4, amp=perc(0.001, 0.06))
    .carriers(1, 3, to='F1').flt(1, 'HP', cutoff=250).dist('soft', drive=0.25, mix=0.4).comp(thresh=-12, ratio=4, attack=1))
for nm, (r2, dec) in (('Perc Blip', (5, 0.12)), ('Perc Blip Low', (3, 0.2)), ('Perc Tick', (9, 0.04)), ('Perc Pop', (2, 0.08))):
    hit(nm, lambda p, r2=r2, dec=dec: p.op(1, ratio=1, level=1, amp=perc(0.001, dec)).op(2, ratio=r2, level=0.6, amp=perc(0.001, dec * 0.3)).pm(2, 1, 0.4).op(3, ratio=2, level=0.4, amp=perc(0.001, dec * 0.6)).op(4, ratio=r2 + 2, level=0.5, amp=perc(0.001, dec * 0.2)).pm(4, 3, 0.3)
        .carriers(1, 3).delay(div='1/16', feedback=0.4, pingpong=True, tone=0.6, mix=0.25).comp(thresh=-12, ratio=4, attack=1))
for nm, (drop, dec) in (('Zap', (48, 0.25)), ('Zap Short', (36, 0.1)), ('Zap Long', (60, 0.5)), ('Zap Up', (-48, 0.3))):
    hit(nm, lambda p, drop=drop, dec=dec: p.op(1, ratio=1, level=1, amp=perc(0.001, dec), pitch=pitch_drop(1.0, dec * 0.7, t=-0.8), pitchamt=drop).op(2, ratio=2, level=0.8, amp=perc(0.001, dec * 0.8)).pm(2, 1, 0.5).fb(2, 0.3)
        .op(3, ratio=3, level=0.5, amp=perc(0.001, dec * 0.6), pitch=pitch_drop(1.0, dec * 0.7, t=-0.8), pitchamt=drop).op(4, ratio=5, level=0.6, amp=perc(0.001, dec * 0.5)).pm(4, 3, 0.4)
        .carriers(1, 3).dist('soft', drive=0.3, mix=0.5).comp(thresh=-12, ratio=4, attack=1))
hit('Noise Burst', lambda p: p.op(1, wave='noise', level=1, amp=perc(0.001, 0.15)).op(2, wave='noise', level=1, amp=perc(0.001, 0.05)).op(3, ratio=1, level=0.5, fixed=True, hz=180, amp=perc(0.001, 0.08), pitch=pitch_drop(0.9, 0.03), pitchamt=24).carriers(1, 2, 3, to='F1').flt(1, 'BP', cutoff=3000, reso=0.4, env=0.6, cut=perc(0.001, 0.1)).comp(thresh=-12, ratio=4, attack=1))
hit('Laser Hit', lambda p: p.op(1, ratio=1, level=1, amp=perc(0.001, 0.2), pitch=pitch_drop(1.0, 0.15, t=-0.9), pitchamt=48).op(2, ratio=7, level=0.7, amp=perc(0.001, 0.15)).pm(2, 1, 0.5).op(3, ratio=1, fine=20, level=0.6, amp=perc(0.001, 0.2), pitch=pitch_drop(1.0, 0.15, t=-0.9), pitchamt=48)
    .carriers(1, 3).delay(div='1/16', feedback=0.5, pingpong=True, mix=0.3).comp(thresh=-12, ratio=4, attack=1))

# ------------------------------------------------------------- FX / RISERS ---
def fxp(name, fn):
    p = P(FXC, name)
    fn(p)
    return p
def riser(name, beats, kind='saw'):
    a = adsr(0.2, 0.1, 1, 0.3, sync=True)
    pitch = env([[0, 0.25], [beats, 1, 0.2], [beats + 1, 1]], sustain=2, sync=True)
    cut = env([[0, 0], [beats, 1, 0.2], [beats + 1, 1]], sustain=2, sync=True)
    def build(p):
        p.mono()
        tone = 0.35 if kind == 'noise' else 1.0
        p.op(1, ratio=1, level=tone, unison=4, detune=20, spread=0.9, amp=a, pitch=pitch, pitchamt=24).op(2, ratio=1, level=0.8, amp=a, pitch=pitch, pitchamt=24).pm(2, 1, 0.45).fb(2, 0.3)
        p.op(3, ratio=2, level=0.5 * tone, amp=a, pitch=pitch, pitchamt=24).op(4, ratio=1, level=0.6, amp=a, pitch=pitch, pitchamt=24).pm(4, 3, 0.35)
        p.op(5, ratio=1.5 if kind == 'chord' else 3, level=(0.5 if kind == 'chord' else 0.3) * tone, amp=a, pitch=pitch, pitchamt=24).op(6, ratio=1, level=0.5, amp=a, pitch=pitch, pitchamt=24).pm(6, 5, 0.3)
        p.carriers(1, 3, 5, to='F1')
        p.op(7, wave='noise', level=1.0 if kind == 'noise' else 0.3, amp=adsr(0.5, 0.1, 1, 0.3, sync=True)).out(7, f1=1 if kind == 'noise' else 0.6).op(8, ratio=0.5, level=0.3, amp=a, pitch=pitch, pitchamt=24)
        p.out(8, dry=0.5 if kind != 'noise' else 0.2)
        p.flt(1, 'BP' if kind == 'noise' else 'LP', cutoff=200 if kind == 'noise' else 300, reso=0.5 if kind == 'noise' else 0.4, slope=12 if kind == 'noise' else 24, env=1.0 if kind == 'noise' else 0.8, cut=cut)
        if kind == 'wobble': p.lfo(1, 'sine', div='1/16').mod('lfo1', 'flt1Cutoff', 0.3).mod('lfo1', 'op1Level', -0.2)
        else: p.lfo(1, 'sine', div='1/16').mod('lfo1', 'op1Level', -0.15)
        p.lfo(2, 'tri', div=('1/1')).mod('lfo2', 'op1Pan', 0.4).mod('lfo2', 'op3Pan', -0.4)
        p.reverb(size=0.85, decay=0.75, mix=0.32).comp(thresh=-12, ratio=4, attack=10)
    return fxp(name, build)
for bars, beats in ((1, 4), (2, 8), (4, 16), (8, 32)):
    riser('Riser %d Bar%s' % (bars, '' if bars == 1 else 's'), beats, 'saw')
    riser('Riser Noise %d Bar%s' % (bars, '' if bars == 1 else 's'), beats, 'noise')
    riser('Riser Wobble %d Bar%s' % (bars, '' if bars == 1 else 's'), beats, 'wobble')
    riser('Riser Chord %d Bar%s' % (bars, '' if bars == 1 else 's'), beats, 'chord')
def downlifter(name, beats, kind='saw'):
    a = adsr(0.01, 0.1, 1, 0.5, sync=True)
    pitch = env([[0, 0.9], [beats, 0.2, -0.3], [beats + 1, 0.2]], sustain=2, sync=True)
    cut = env([[0, 0], [beats, 1, -0.3], [beats + 1, 1]], sustain=2, sync=True)
    fxp(name, lambda p: (p.mono().op(1, ratio=1, level=1, unison=3, detune=15, spread=0.9, amp=a, pitch=pitch, pitchamt=24).op(2, ratio=1, level=0.8, amp=a, pitch=pitch, pitchamt=24).pm(2, 1, 0.45)
        .op(3, ratio=2, level=0.4, amp=a, pitch=pitch, pitchamt=24).op(4, ratio=1, level=0.6, amp=a).pm(4, 3, 0.3).op(5, wave='noise', level=0.5 if kind == 'noise' else 0.3, amp=a).op(6, ratio=0.5, level=0.4, amp=a, pitch=pitch, pitchamt=24)
        .carriers(1, 3, to='F1').out(5, f1=1).out(6, dry=0.5).flt(1, 'LP', cutoff=8000, reso=0.4, slope=24, env=-0.8, cut=cut).reverb(size=0.8, decay=0.7, mix=0.3).comp(thresh=-12, ratio=4, attack=10)))
for bars, beats in ((1, 4), (2, 8), (4, 16)):
    downlifter('Downlifter %d Bar%s' % (bars, '' if bars == 1 else 's'), beats)
    downlifter('Downlifter Noise %d Bar%s' % (bars, '' if bars == 1 else 's'), beats, 'noise')
for nm, (hz, dec) in (('Impact Boom', (45, 2.5)), ('Impact Deep', (36, 3.5)), ('Impact Short', (55, 1.2)), ('Impact Metal', (70, 2.0))):
    fxp(nm, lambda p, hz=hz, dec=dec, nm=nm: (p.op(1, ratio=1, level=1, fixed=True, hz=hz, amp=perc(0.002, dec, t=-0.4), pitch=pitch_drop(0.9, 0.08), pitchamt=36).op(2, ratio=1, level=0.6, fixed=True, hz=hz * 2, amp=perc(0.002, dec * 0.4)).pm(2, 1, 0.4 if 'Metal' in nm else 0.2)
        .op(3, wave='noise', level=0.6, amp=perc(0.001, 0.6, t=-0.6)).op(4, ratio=1, level=0.5, fixed=True, hz=hz * 3.7, amp=perc(0.001, dec * 0.3)).op(5, ratio=1, level=0.5, fixed=True, hz=hz * 5.3, amp=perc(0.001, dec * 0.3)).rm(4, 5, 0.6 if 'Metal' in nm else 0.0)
        .carriers(1, 4).out(3, f1=1).flt(1, 'LP', cutoff=800, reso=0.3, slope=24, env=0.5, cut=perc(0.001, 0.3)).dist('soft', drive=0.4, tone=0.4, mix=0.5).reverb(size=0.9, decay=0.8, mix=0.4).eq(low=3, lowf=50, lowcut=25).comp(thresh=-12, ratio=6, attack=3, limit=True)))
for nm, (hz, dec) in (('Sub Drop', (60, 3.0)), ('Sub Drop Short', (70, 1.5)), ('Sub Drop Long', (55, 5.0))):
    fxp(nm, lambda p, hz=hz, dec=dec: p.mono().op(1, ratio=1, level=1, amp=perc(0.005, dec, t=-0.3), pitch=env([[0, 1], [dec * 0.8, 0.0, -0.4], [dec, 0]], sustain=-1), pitchamt=36, fixed=True, hz=hz)
        .op(2, ratio=1, level=0.4, amp=perc(0.005, dec * 0.6), fixed=True, hz=hz * 2, pitch=env([[0, 1], [dec * 0.8, 0.0, -0.4], [dec, 0]], sustain=-1), pitchamt=36).pm(2, 1, 0.2)
        .op(3, wave='noise', level=0.3, amp=perc(0.001, 0.08)).op(4, ratio=1, level=0.3, fixed=True, hz=hz * 3, amp=perc(0.01, dec * 0.3), pitch=env([[0, 1], [dec * 0.8, 0.0, -0.4], [dec, 0]], sustain=-1), pitchamt=36).rm(4, 1, 0.3)
        .carriers(1, 3, 4).eq(low=2, lowf=45, lowcut=22).comp(thresh=-10, ratio=4, attack=10))
for nm, (drop, dec, r2) in (('Laser Zap', (48, 0.3, 3)), ('Laser Zap Long', (60, 0.6, 3)), ('Laser Zap High', (36, 0.25, 7)), ('Laser Rise', (-48, 0.4, 3)), ('Laser Zap Double', (48, 0.35, 5))):
    fxp(nm, lambda p, drop=drop, dec=dec, r2=r2: p.op(1, ratio=1, level=1, amp=perc(0.001, dec), pitch=pitch_drop(1.0, dec * 0.8, t=-0.8), pitchamt=drop).op(2, ratio=r2, level=0.8, amp=perc(0.001, dec * 0.8)).pm(2, 1, 0.5).fb(2, 0.4)
        .op(3, ratio=2, level=0.5, amp=perc(0.001, dec), pitch=pitch_drop(1.0, dec * 0.8, t=-0.8), pitchamt=drop).op(4, ratio=r2 * 2, level=0.6, amp=perc(0.001, dec * 0.6)).pm(4, 3, 0.4).rm(4, 1, 0.2)
        .carriers(1, 3).delay(div='1/16', feedback=0.5, pingpong=True, tone=0.6, mix=0.3).comp(thresh=-12, ratio=4, attack=1))
for nm, (rate, wave) in (('Siren', (0.6, 'tri')), ('Siren Fast', (2.5, 'tri')), ('Siren Police', (0.9, 'square')), ('Siren Air Raid', (0.15, 'sine'))):
    fxp(nm, lambda p, rate=rate, wave=wave: p.mono().op(1, ratio=1, level=1, amp=adsr(0.05, 0.1, 1, 0.2)).op(2, ratio=2, level=0.6, amp=adsr(0.05, 0.1, 1, 0.2)).pm(2, 1, 0.3).op(3, ratio=1.5, level=0.5, amp=adsr(0.05, 0.1, 1, 0.2)).op(4, ratio=3, level=0.5, amp=adsr(0.05, 0.1, 1, 0.2)).pm(4, 3, 0.25)
        .carriers(1, 3).lfo(1, wave, rate=rate).mod('lfo1', 'op1Fine', 1.0).mod('lfo1', 'op2Fine', 1.0).mod('lfo1', 'op3Fine', 1.0).mod('lfo1', 'op4Fine', 1.0).delay(div='1/4', feedback=0.4, pingpong=True, mix=0.25).reverb(size=0.7, decay=0.6, mix=0.25))
for nm, div in (('Alarm', '1/8'), ('Alarm Fast', '1/16'), ('Alarm Slow', '1/4')):
    fxp(nm, lambda p, div=div: p.mono().op(1, partials=[1, 0, 0.33, 0, 0.2], level=1, amp=adsr(0.005, 0.1, 1, 0.05)).op(2, ratio=1.5, level=0.7, amp=adsr(0.005, 0.1, 1, 0.05)).op(3, ratio=2, level=0.5, amp=adsr(0.005, 0.1, 1, 0.05)).op(4, ratio=3, level=0.5, amp=adsr(0.005, 0.1, 1, 0.05)).pm(4, 3, 0.3)
        .carriers(1, 2, 3).lfo(1, 'square', div=div).mod('lfo1', 'op1Fine', 0.5).mod('lfo1', 'op2Fine', 0.5).mod('lfo1', 'op3Fine', 0.5).dist('hard', drive=0.3, mix=0.5).delay(div='1/8', feedback=0.3, mix=0.2))
for nm, div in (('Glitch S&H', '1/16'), ('Glitch S&H Fast', '1/32'), ('Glitch S&H Slow', '1/8'), ('Glitch Stutter', '1/16T')):
    fxp(nm, lambda p, div=div: p.op(1, ratio=1, level=1, amp=adsr(0.005, 0.1, 1, 0.1)).op(2, ratio=2, level=0.8, amp=adsr(0.005, 0.1, 1, 0.1)).pm(2, 1, 0.45).op(3, ratio=3, level=0.5, amp=adsr(0.005, 0.1, 1, 0.1)).op(4, ratio=5, level=0.6, amp=adsr(0.005, 0.1, 1, 0.1)).pm(4, 3, 0.4).rm(4, 1, 0.3)
        .carriers(1, 3, to='F1').flt(1, 'LP', cutoff=1500, reso=0.5).lfo(1, 'sh', div=div).mod('lfo1', 'op1Fine', 1.0).mod('lfo1', 'op2Fine', 1.0).mod('lfo1', 'op3Fine', 1.0).mod('lfo1', 'flt1Cutoff', 0.4)
        .lfo(2, 'square', div=div).mod('lfo2', 'op1Level', -0.4).mod('lfo2', 'op3Level', 0.4).dist('crush', drive=0.4, mix=0.6).delay(div='1/16', feedback=0.5, pingpong=True, mix=0.3))
fxp('Dial-up', lambda p: p.op(1, ratio=1, level=1, amp=adsr(0.005, 0.1, 1, 0.05)).op(2, ratio=3, level=0.7, amp=adsr(0.005, 0.1, 1, 0.05)).pm(2, 1, 0.4).op(3, ratio=2, level=0.6, amp=adsr(0.005, 0.1, 1, 0.05)).op(4, ratio=7, level=0.5, amp=adsr(0.005, 0.1, 1, 0.05)).pm(4, 3, 0.4)
    .carriers(1, 3).lfo(1, 'sh', rate=14).mod('lfo1', 'op1Fine', 1.0).mod('lfo1', 'pm21', 0.3).lfo(2, 'sh', rate=23).mod('lfo2', 'op2Fine', 1.0).mod('lfo2', 'op3Fine', 1.0).dist('crush', drive=0.3, mix=0.5))
fxp('Robot Talk', lambda p: p.op(1, ratio=1, level=1, amp=adsr(0.005, 0.1, 1, 0.05)).op(2, ratio=1, level=0.8, amp=adsr(0.005, 0.1, 1, 0.05)).pm(2, 1, 0.45).fb(2, 0.3).op(3, ratio=2, level=0.5, amp=adsr(0.005, 0.1, 1, 0.05)).rm(3, 1, 0.5)
    .carriers(1, to='F1').out(1, f2=0.8).flt(1, 'BP', cutoff=500, reso=0.7).flt(2, 'BP', cutoff=1500, reso=0.7).lfo(1, 'sh', rate=9).mod('lfo1', 'flt1Cutoff', 0.5).mod('lfo1', 'flt2Cutoff', -0.5).lfo(2, 'sh', rate=13).mod('lfo2', 'op1Fine', 0.5).dist('hard', drive=0.3, mix=0.5))
for nm, (hz, dec) in (('Thunder', (40, 3.0)), ('Thunder Close', (50, 2.0)), ('Thunder Rumble', (35, 5.0))):
    fxp(nm, lambda p, hz=hz, dec=dec: p.op(1, wave='noise', level=1, amp=env([[0, 0], [0.2, 1, 0.3], [dec * 0.4, 0.5, -0.3], [dec, 0, -0.5]], sustain=-1)).op(2, ratio=1, level=0.8, fixed=True, hz=hz, amp=perc(0.1, dec, t=-0.3))
        .op(3, wave='noise', level=0.6, amp=env([[0, 0], [0.5, 1, 0.3], [dec, 0, -0.5]], sustain=-1)).carriers(2).out(1, f1=1).out(3, f2=1).flt(1, 'LP', cutoff=400, reso=0.3, slope=24).flt(2, 'LP', cutoff=150, slope=24)
        .lfo(1, 'sh', rate=9).mod('lfo1', 'flt1Cutoff', 0.3).mod('lfo1', 'op3Level', 0.3).reverb(size=0.95, decay=0.85, mix=0.4).eq(low=3, lowf=50).comp(thresh=-12, ratio=4, attack=10))
for nm, (div, ftype) in (('Air Sweep 1 Bar', ('1/1', 'BP')), ('Air Sweep 2 Bars', ('1/2', 'BP')), ('Air Sweep HP', ('1/1', 'HP')), ('Air Sweep LP', ('1/1', 'LP'))):
    fxp(nm, lambda p, div=div, ftype=ftype: p.mono().op(1, wave='noise', level=1, amp=adsr(0.3, 0.2, 0.9, 1.0)).op(2, wave='noise', level=0.6, amp=adsr(0.6, 0.2, 0.9, 1.2)).op(3, ratio=1, level=0.15, unison=4, detune=30, amp=adsr(0.8, 0.2, 0.9, 1.2)).op(4, ratio=1, level=0.6, amp=adsr(0.8, 0.2, 0.9, 1.2)).pm(4, 3, 0.5).fb(4, 0.4).carriers(1, 2, 3, to='F1').out(2, f2=1)
        .flt(1, ftype, cutoff=800, reso=0.6, slope=12).flt(2, 'BP', cutoff=2500, reso=0.5).lfo(1, 'tri', div=div).mod('lfo1', 'flt1Cutoff', 0.6).mod('lfo1', 'flt2Cutoff', -0.4).lfo(2, 'sine', rate=0.4).mod('lfo2', 'op1Pan', 0.6).reverb(size=0.8, decay=0.7, mix=0.35).comp(thresh=-12, ratio=4, attack=10))
for nm, beats in (('Reverse Swell 1 Bar', 4), ('Reverse Swell 2 Bars', 8), ('Reverse Swell Cymbal', 4)):
    fxp(nm, lambda p, beats=beats, nm=nm: p.op(1, wave='noise' if 'Cymbal' in nm else 'saw', level=1, unison=1 if 'Cymbal' in nm else 3, detune=14, amp=env([[0, 0], [beats, 1, 0.6], [beats + 0.1, 0]], sustain=-1, sync=True))
        .op(2, ratio=1, level=0.7, amp=env([[0, 0], [beats, 1, 0.6], [beats + 0.1, 0]], sustain=-1, sync=True)).pm(2, 1, 0.0 if 'Cymbal' in nm else 0.3).op(3, ratio=1, level=0.6, fixed=True, hz=5300, amp=env([[0, 0], [beats, 1, 0.6], [beats + 0.1, 0]], sustain=-1, sync=True))
        .op(4, ratio=1, level=0.6, fixed=True, hz=7900, amp=env([[0, 0], [beats, 1, 0.6], [beats + 0.1, 0]], sustain=-1, sync=True)).rm(3, 4, 0.8 if 'Cymbal' in nm else 0.0)
        .op(3, fixed='Cymbal' in nm, ratio=2).op(4, fixed='Cymbal' in nm, ratio=3).pm(4, 3, 0.0 if 'Cymbal' in nm else 0.35).pm(2, 1, 0.3)
        .carriers(1, 3, to='F1').flt(1, 'HP' if 'Cymbal' in nm else 'LP', cutoff=3000 if 'Cymbal' in nm else 600, reso=0.3, env=0.8, cut=env([[0, 0], [beats, 1, 0.5], [beats + 1, 1]], sustain=2, sync=True))
        .reverb(size=0.9, decay=0.8, mix=0.4).comp(thresh=-12, ratio=4, attack=10))
fxp('Wind', lambda p: p.op(1, wave='noise', level=1, amp=adsr(1.5, 0.5, 0.9, 2.0)).op(2, wave='noise', level=0.7, amp=adsr(2.0, 0.5, 0.9, 2.0)).op(3, ratio=1, level=0.12, fixed=True, hz=90, amp=adsr(2.5, 0.5, 0.9, 2.0)).op(4, ratio=1, level=0.6, fixed=True, hz=35, amp=adsr(2.5, 0.5, 0.9, 2.0)).pm(4, 3, 0.4).carriers(1, 3, to='F1').out(2, f2=1).flt(1, 'BP', cutoff=600, reso=0.7).flt(2, 'BP', cutoff=1800, reso=0.6)
    .lfo(1, 'sine', rate=0.13).mod('lfo1', 'flt1Cutoff', 0.4).mod('lfo1', 'op1Level', 0.3).lfo(2, 'sine', rate=0.21).mod('lfo2', 'flt2Cutoff', 0.4).mod('lfo2', 'op1Pan', 0.5).reverb(size=0.9, decay=0.8, mix=0.4))
fxp('Rain', lambda p: p.op(1, wave='noise', level=0.8, amp=adsr(1.0, 0.5, 0.9, 1.5)).op(2, wave='noise', level=0.6, amp=adsr(0.5, 0.5, 0.9, 1.5)).op(3, wave='noise', level=0.5, amp=adsr(0.8, 0.5, 0.9, 1.5)).carriers(1, 3, to='F1').out(2, f2=1).out(3, f1=0, f3=1).flt(3, 'HP', cutoff=9000).flt(1, 'HP', cutoff=3000, reso=0.2).flt(2, 'BP', cutoff=6000, reso=0.3)
    .lfo(1, 'sh', rate=25).mod('lfo1', 'op2Level', 0.6).mod('lfo1', 'flt2Cutoff', 0.3).reverb(size=0.7, decay=0.6, mix=0.3))
fxp('Helicopter', lambda p: p.mono().op(1, wave='noise', level=1, amp=adsr(0.5, 0.2, 0.9, 0.5)).op(2, ratio=1, level=0.6, fixed=True, hz=70, amp=adsr(0.5, 0.2, 0.9, 0.5)).op(3, ratio=1, level=0.5, fixed=True, hz=140, amp=adsr(0.5, 0.2, 0.9, 0.5)).pm(3, 2, 0.4).carriers(1, 2, to='F1').flt(1, 'LP', cutoff=900, reso=0.5)
    .lfo(1, 'square', rate=12).mod('lfo1', 'op1Level', -0.6).mod('lfo1', 'flt1Cutoff', 0.3).lfo(2, 'sine', rate=0.5).mod('lfo2', 'op1Pan', 0.8).dist('soft', drive=0.3, mix=0.5).reverb(size=0.6, decay=0.5, mix=0.2))
fxp('Telephone Ring', lambda p: p.op(1, ratio=1, level=1, fixed=True, hz=440, amp=adsr(0.005, 0.1, 1, 0.05)).op(2, ratio=1, level=0.8, fixed=True, hz=480, amp=adsr(0.005, 0.1, 1, 0.05)).op(3, ratio=1, level=0.5, fixed=True, hz=1320, amp=adsr(0.005, 0.1, 1, 0.05)).pm(3, 1, 0.2).op(4, ratio=1, level=0.5, fixed=True, hz=1440, amp=adsr(0.005, 0.1, 1, 0.05)).pm(4, 2, 0.2)
    .carriers(1, 2, to='F1').flt(1, 'BP', cutoff=1200, reso=0.4).lfo(1, 'square', rate=20).mod('lfo1', 'op1Level', -0.5).mod('lfo1', 'op2Level', -0.5).dist('crush', drive=0.3, mix=0.4))
fxp('Space Ship', lambda p: p.mono().op(1, ratio=1, level=1, unison=4, detune=30, amp=adsr(1.0, 0.5, 1, 1.0)).op(2, ratio=1, level=0.8, amp=adsr(1.0, 0.5, 1, 1.0)).pm(2, 1, 0.4).fb(2, 0.5).op(3, ratio=0.5, level=0.6, amp=adsr(1.0, 0.5, 1, 1.0)).rm(3, 1, 0.4)
    .carriers(1, 3, to='F1').flt(1, 'BP', cutoff=700, reso=0.7).lfo(1, 'sine', rate=0.3).mod('lfo1', 'flt1Cutoff', 0.5).mod('lfo1', 'op1Fine', 0.2).lfo(2, 'tri', rate=7).mod('lfo2', 'pm21', 0.2).phaser(rate=0.4, depth=0.8, stages=2, feedback=0.6, mix=0.5).reverb(size=0.95, decay=0.9, mix=0.45))
fxp('Vinyl Crackle', lambda p: p.op(1, wave='noise', level=1, amp=adsr(0.01, 0.1, 1, 0.1)).op(2, wave='noise', level=0.5, amp=adsr(0.01, 0.1, 1, 0.1)).op(3, ratio=1, level=0.15, fixed=True, hz=60, amp=adsr(0.01, 0.1, 1, 0.1)).carriers(1, 3, to='F1').out(2, f2=1).flt(1, 'HP', cutoff=4000).flt(2, 'LP', cutoff=300)
    .lfo(1, 'sh', rate=35).mod('lfo1', 'op1Level', -0.9).mod('lfo1', 'op2Level', -0.7).dist('crush', drive=0.5, tone=0.4, mix=0.5))

# ================================================================== output ====
def main():
    names = [p.name for p in PRESETS]
    dup = {n for n in names if names.count(n) > 1}
    assert not dup, 'duplicate preset names: %s' % dup
    assert len(PRESETS) >= 1000, 'expected at least 1000 presets, have %d' % len(PRESETS)

    trims = {}
    if os.path.exists(TRIMS):
        with open(TRIMS, encoding='utf-8') as f: trims = json.load(f)
    if len(sys.argv) >= 3 and sys.argv[1] == '--match':
        with open(sys.argv[2], encoding='utf-8-sig') as f: loud = json.load(f)   # PowerShell redirects write a BOM
        held = 0
        for row in loud:
            name = row['name']
            if name == 'Init': continue
            # the measurement includes the trim the file had: move from there to the target
            want = trims.get(name, 0.0) + (TARGET_DB - row['dB'])
            peak_at_want = row['peak'] * (10 ** ((want - trims.get(name, 0.0)) / 20))
            if peak_at_want > PEAK_LIMIT:
                want -= 20 * math.log10(peak_at_want / PEAK_LIMIT)
                held += 1
            trims[name] = round(max(-24.0, min(12.0, want)), 2)
        with open(TRIMS, 'w', encoding='utf-8') as f: json.dump(trims, f, indent=1, sort_keys=True)
        print('matched %d presets to %.1f dBFS (%d held back for peaks)' % (len(loud) - 1, TARGET_DB, held))

    CAT_ORDER = [INIT, KEYS, ORCH, DUB, BASS, LEAD, PAD, PLUCK, EKEYS, STAB, DRUM, FXC]
    cats = []
    for p in PRESETS:
        if p.name in trims: p.p['presetGain'] = trims[p.name]
        if p.cat not in cats: cats.append(p.cat)
    cats.sort(key=lambda c: CAT_ORDER.index(c) if c in CAT_ORDER else 99)
    # every preset must use the matrix: at least 5 operators in the signal path
    thin = []
    for p in PRESETS:
        if p.name == 'Init': continue
        used = set()
        for k in range(1, 9):
            routed = any(p.p.get('out%d%s' % (k, b), 0) > 0 for b in ('Dry', 'F1', 'F2', 'F3'))
            mods = any(p.p.get('pm%d%d' % (k, d), 0) > 0 or p.p.get('rm%d%d' % (k, d), 0) > 0 for d in range(1, 9))
            if (routed or mods) and p.p.get('op%dLevel' % k, 1) > 0: used.add(k)
        need = 3 if p.cat in (DRUM, FXC) else 5
        if len(used) < need: thin.append('%s (%d)' % (p.name, len(used)))
    assert not thin, 'presets using too few operators: ' + ', '.join(thin)
    doc = {
        'format': 'Eight Ball Factory Presets',
        'version': 1,
        'note': 'GENERATED by presets/make_presets.py: edit the recipes there, not this file. Every preset is an 8-operator architecture. Values = parameter defaults <- '
                'the preset\'s params; model blocks (waves, envs, lfoShapes) likewise. Envelope points are [time s, level 0..1, '
                'tension -1..1] with absolute times; levels for pitch/mod envelopes: 0.5 = neutral. modDst names a mod slot\'s '
                'destination by parameter id. presetGain is the level trim from the matching pass (presets/trims.json).',
        'templates': {'init': {'params': {}}},
        'categories': [{'name': c, 'presets': [p.to_json() for p in PRESETS if p.cat == c]} for c in cats],
    }
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, indent=1)
        f.write('\n')
    print('wrote %s: %d presets in %d categories (%s)' % (OUT, len(PRESETS), len(cats), ', '.join('%s %d' % (c, sum(1 for p in PRESETS if p.cat == c)) for c in cats)))

if __name__ == '__main__':
    main()
