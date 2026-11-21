#!/usr/bin/env python3
"""
Generates vst/presets/factory_presets.json (the factory presets) from the recipes below.
Do not edit the JSON by hand: edit a recipe here and run

    python make_presets.py                      writes factory_presets.json (keeps the stored level trims)
    python make_presets.py --match loud.json    reads EightBallTests --loudness output and sets every
                                                preset's presetGain so its loudest 100 ms sits at TARGET_DB
                                                (peaks are kept below PEAK_LIMIT), then writes the JSON

Level matching loop (from vst/):
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
INIT = 'Init'; KEYS = 'Pianos & Keys'; ORCH = 'Orchestral & Acoustic'; DUB = 'Dubstep Bass'; BASS = 'Bass'
LEAD = 'Leads'; PAD = 'Pads & Textures'; PLUCK = 'Plucks & Arps'; EKEYS = 'Synth Keys & Organs'
STAB = 'Chords & Stabs'; DRUM = 'Drums & Percussion'; FXC = 'FX & Risers'

P(INIT, 'Init')

# ---------------------------------------------------------------- pianos ------
def piano(name, bright=0.42, hammer=0.25, detune=4, soft=False, honky=False):
    p = P(KEYS, name)
    p.op(1, ratio=1, level=0.9, vel=0.6, amp=adsr(0.002, 3.0, 0.0, 0.25, t=-0.6))
    p.op(2, ratio=1, level=0.6, vel=0.95, amp=perc(0.002, 1.2)).pm(2, 1, bright)
    p.op(3, ratio=1, fine=detune, level=0.55, vel=0.6, amp=adsr(0.002, 2.5, 0.0, 0.25, t=-0.6))
    p.op(4, ratio=7, level=0.4, vel=1.0, amp=perc(0.001, 0.09)).pm(4, 1, hammer).pm(4, 3, hammer * 0.6)
    p.op(5, ratio=2, level=0.35, vel=0.8, amp=perc(0.002, 1.6)).pm(2, 5, bright * 0.5)
    p.carriers(1, 3, 5, level=0.8)
    if honky: p.op(3, fine=22).op(1, fine=-10)
    if soft: p.flt(1, 'LP', cutoff=2600, key=0.5, vel=0.4).carriers(1, 3, 5, level=0.8, to='F1').out(1, dry=0)
    p.eq(low=1.5, lowf=120, high=1.5, highf=6000).reverb(size=0.5, decay=0.4, mix=0.12)
    return p
piano('Grand Piano')
piano('Bright Piano', bright=0.5, hammer=0.32)
piano('Soft Piano', bright=0.32, hammer=0.18, soft=True)
piano('Honky Tonk', bright=0.46, honky=True).chorus(rate=0.3, depth=0.2, mix=0.25)

p = P(KEYS, 'Harpsichord')
p.op(1, ratio=1, level=0.9, vel=0.3, amp=perc(0.001, 1.4)).op(2, ratio=1, level=0.85, vel=0.4, amp=perc(0.001, 0.9)).pm(2, 1, 0.55).fb(2, 0.2)
p.op(3, ratio=3, level=0.4, amp=perc(0.001, 0.5)).pm(3, 1, 0.3).op(4, ratio=2, level=0.5, amp=perc(0.001, 1.2)).carriers(1, 4, level=0.8)
p.eq(low=-2, lowf=150, high=3, highf=5000).reverb(size=0.4, decay=0.35, mix=0.14)

p = P(KEYS, 'Clavinet')
p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.001, 1.5, 0.0, 0.08, t=-0.6)).op(2, ratio=1, level=0.8, vel=0.9, amp=perc(0.001, 0.35)).pm(2, 1, 0.58)
p.op(3, ratio=5, level=0.35, vel=1, amp=perc(0.001, 0.05)).pm(3, 1, 0.22).carriers(1, to='F1')
p.flt(1, 'LP', cutoff=1800, reso=0.35, env=0.45, vel=0.3, key=0.4, cut=perc(0.001, 0.25)).eq(mid=3, midf=1800, q=1.2).comp(thresh=-18, ratio=3, attack=5)

def epiano(name, tine=0.3, body=0.45, drive=0.0, trem=0.0):
    p = P(KEYS, name)
    p.op(1, ratio=1, level=1, vel=0.55, amp=adsr(0.002, 3.5, 0.0, 0.3, t=-0.6))
    p.op(2, ratio=14, level=0.35, vel=0.95, amp=perc(0.002, 0.3)).pm(2, 1, tine)
    p.op(3, ratio=1, level=0.8, vel=0.5, amp=adsr(0.002, 3.0, 0.0, 0.3, t=-0.6))
    p.op(4, ratio=1, level=0.6, vel=0.85, amp=perc(0.002, 1.6)).pm(4, 3, body)
    p.carriers(1, 3, level=0.7)
    if trem: p.lfo(1, 'sine', rate=5.2).mod('lfo1', 'op1Pan', trem).mod('lfo1', 'op3Pan', -trem)
    if drive: p.dist('soft', drive=drive, tone=0.7, mix=0.6)
    p.chorus(rate=0.5, depth=0.25, mix=0.25).reverb(size=0.5, decay=0.4, mix=0.15)
    return p
epiano('Rhodes Tine', trem=0.5)
epiano('Wurli', tine=0.2, body=0.55, drive=0.25, trem=0.35).eq(mid=2, midf=1200)
epiano('DX Piano', tine=0.4, body=0.5).op(5, ratio=1, fine=6, level=0.5, amp=adsr(0.002, 2.5, 0.0, 0.3)).out(5, dry=0.5)

p = P(KEYS, 'Toy Piano')
p.op(1, ratio=1, level=0.8, amp=perc(0.001, 1.2)).op(2, ratio=4, fine=20, level=0.5, amp=perc(0.001, 0.4)).pm(2, 1, 0.3)
p.op(3, ratio=10, fine=-30, level=0.3, amp=perc(0.001, 0.2)).pm(3, 1, 0.15).op(4, ratio=3, level=0.4, amp=perc(0.001, 0.9)).carriers(1, 4, level=0.8)
p.eq(low=-4, lowf=200).reverb(size=0.3, decay=0.3, mix=0.15)

p = P(KEYS, 'Music Box')
p.op(1, ratio=1, level=0.8, amp=perc(0.001, 2.0)).op(2, ratio=4, level=0.5, amp=perc(0.001, 0.5)).pm(2, 1, 0.33)
p.op(3, ratio=8, level=0.25, amp=perc(0.001, 0.2)).pm(3, 1, 0.12).carriers(1).eq(low=-6, lowf=300).reverb(size=0.6, decay=0.5, mix=0.25)

# ------------------------------------------------------------ orchestral ------
def vibrato(p, rate=5.5, delay=0.35, cents=0.12, ops=(1, 2)):
    p.lfo(2, 'sine', rate=rate, delay=delay)
    for k in ops: p.mod('lfo2', 'op%dFine' % k, cents)
    return p

def strings(name, cat=ORCH, attack=0.35, release=0.6, cutoff=3500, unison=4, detune=12, lo=False, pizz=False):
    p = P(cat, name)
    if pizz:
        a = perc(0.003, 0.5)
    else:
        a = adsr(attack, 0.3, 0.9, release, t=0.2)
    p.op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.8, vel=0.4, amp=a)
    p.op(2, ratio=1, level=0.7, vel=0.5, amp=a).pm(2, 1, 0.42).fb(2, 0.25)
    p.op(3, ratio=3 if not lo else 2, level=0.35, amp=a).pm(3, 1, 0.18)
    p.carriers(1, to='F1').flt(1, 'LP', cutoff=cutoff, key=0.4, vel=0.3, reso=0.1, env=0.25 if pizz else 0.0, cut=perc(0.002, 0.3) if pizz else None)
    if not pizz: vibrato(p, ops=(1, 2), cents=0.08)
    p.chorus(rate=0.4, depth=0.3, mix=0.3).reverb(size=0.75, decay=0.65, mix=0.22)
    return p
strings('Violin', unison=1, attack=0.12, cutoff=5000).eq(mid=2.5, midf=2600, q=1.5)
strings('Viola', unison=1, attack=0.14, cutoff=3800).eq(mid=2, midf=1800, q=1.5)
strings('Cello', unison=1, attack=0.15, cutoff=2600, lo=True).eq(low=2, lowf=180)
strings('Double Bass', unison=1, attack=0.08, cutoff=1400, lo=True).eq(low=3, lowf=100)
strings('String Section')
strings('Pizzicato', unison=1, pizz=True, cutoff=2500)

p = P(ORCH, 'Harp')
p.op(1, ratio=1, level=0.9, vel=0.5, amp=perc(0.002, 2.2)).op(2, ratio=2, level=0.5, vel=0.9, amp=perc(0.002, 0.9)).pm(2, 1, 0.3)
p.op(3, ratio=5, level=0.3, vel=1, amp=perc(0.001, 0.15)).pm(3, 1, 0.14).carriers(1).reverb(size=0.7, decay=0.6, mix=0.28)

def wind(name, pm=0.12, ratio2=1, attack=0.08, breath=0.12, cutoff=5000, odd=False, formant=None, cat=ORCH):
    p = P(cat, name)
    a = adsr(attack, 0.2, 0.9, 0.12, t=0.2)
    if odd: p.op(1, partials=[1, 0, 0.33, 0, 0.2, 0, 0.14, 0, 0.1], level=1, vel=0.4, amp=a)
    else:   p.op(1, ratio=1, level=1, vel=0.4, amp=a)
    p.op(2, ratio=ratio2, level=0.6, vel=0.6, amp=a, mod=swell(0.15, 0.3, 0.6)).pm(2, 1, pm)
    p.op(3, wave='noise', level=breath, vel=0.7, amp=perc(0.005, 0.12)).out(3, f2=1)
    p.flt(2, 'BP', cutoff=2500, reso=0.5)
    p.carriers(1, to='F1').flt(1, 'LP', cutoff=cutoff, key=0.5)
    if formant: p.flt(1, 'BP', cutoff=formant, reso=0.45, mix=0.6)
    vibrato(p, ops=(1,), cents=0.1, delay=0.45)
    p.reverb(size=0.55, decay=0.5, mix=0.2)
    return p
wind('Flute', pm=0.1)
wind('Piccolo', pm=0.08, attack=0.05, breath=0.18, cutoff=9000)
wind('Oboe', pm=0.3, ratio2=2, attack=0.05, breath=0.04, formant=1200)
wind('Clarinet', pm=0.15, ratio2=3, attack=0.06, breath=0.03, odd=True, cutoff=3000)
wind('Bassoon', pm=0.35, ratio2=1, attack=0.07, breath=0.05, cutoff=1500, formant=550)
wind('Pan Flute', pm=0.06, attack=0.04, breath=0.3, cutoff=4000).op(3, amp=perc(0.003, 0.08), level=0.3)

def brass(name, pm=0.5, attack=0.05, cutoff=3500, unison=1, detune=8, ratio3=2, cat=ORCH, lo=False):
    p = P(cat, name)
    a = adsr(attack, 0.25, 0.85, 0.15, t=0.2)
    p.op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.7, vel=0.4, amp=a)
    p.op(2, ratio=1, level=0.8, vel=0.8, amp=a, mod=swell(0.12, 0.35, 0.6)).pm(2, 1, pm).fb(2, 0.15)
    p.op(3, ratio=ratio3, level=0.4, vel=0.7, amp=a).pm(3, 2, 0.25)
    p.carriers(1, to='F1').flt(1, 'LP', cutoff=cutoff, key=0.5, vel=0.4, env=0.2, cut=adsr(0.08, 0.3, 0.6, 0.2))
    if lo: p.eq(low=2.5, lowf=120)
    vibrato(p, ops=(1, 2), cents=0.06, delay=0.5)
    p.reverb(size=0.6, decay=0.5, mix=0.18)
    return p
brass('Trumpet', pm=0.55, cutoff=5000)
brass('French Horn', pm=0.32, attack=0.1, cutoff=1800, ratio3=1)
brass('Trombone', pm=0.45, attack=0.07, cutoff=2600)
brass('Tuba', pm=0.3, attack=0.08, cutoff=900, lo=True)
brass('Brass Section', pm=0.48, unison=3, detune=10, cutoff=3200).chorus(rate=0.35, depth=0.3, mix=0.3)

def guitar(name, pm=0.35, pick=0.15, decay=2.0, cutoff=3500, lo=False):
    p = P(ORCH, name)
    p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.002, decay, 0.0, 0.15, t=-0.6))
    p.op(2, ratio=1, level=0.75, vel=0.9, amp=perc(0.002, decay * 0.35)).pm(2, 1, pm).fb(2, 0.12)
    p.op(3, ratio=3, level=0.4, vel=1, amp=perc(0.001, 0.12)).pm(3, 1, pick)
    p.carriers(1, to='F1').flt(1, 'LP', cutoff=cutoff, key=0.4, env=0.3, vel=0.3, cut=perc(0.002, 0.4))
    if lo: p.eq(low=3, lowf=90).comp(thresh=-16, ratio=3, attack=8)
    p.reverb(size=0.45, decay=0.4, mix=0.14)
    return p
guitar('Nylon Guitar')
guitar('Steel Guitar', pm=0.5, pick=0.2, cutoff=5000).eq(high=2, highf=5000)
guitar('Bass Guitar', pm=0.42, pick=0.1, decay=2.5, cutoff=1500, lo=True)

def mallet(name, ratio=4, pm=0.3, hit=0.12, decay=0.7, trem=0.0, bright_ratio=None, bright=0.12, cat=ORCH):
    p = P(cat, name)
    p.op(1, ratio=1, level=1, vel=0.5, amp=perc(0.001, decay))
    p.op(2, ratio=ratio, level=0.6, vel=0.9, amp=perc(0.001, hit)).pm(2, 1, pm)
    if bright_ratio: p.op(3, ratio=bright_ratio, level=0.4, vel=0.8, amp=perc(0.001, decay * 0.4)).pm(3, 1, bright)
    p.carriers(1)
    if trem: p.lfo(1, 'sine', rate=4.5).mod('lfo1', 'op1Level', trem)
    p.reverb(size=0.5, decay=0.45, mix=0.2)
    return p
mallet('Marimba', ratio=4, pm=0.35, hit=0.1, decay=0.8).eq(low=2, lowf=150)
mallet('Vibraphone', ratio=4, pm=0.22, hit=1.5, decay=3.0, trem=-0.3).chorus(rate=0.2, depth=0.2, mix=0.2)
mallet('Glockenspiel', ratio=7, pm=0.28, hit=0.35, decay=1.6, bright_ratio=10).eq(low=-6, lowf=400)
mallet('Tubular Bells', ratio=3.5, pm=0.5, hit=2.5, decay=5.0, bright_ratio=1.5, bright=0.3).reverb(size=0.85, decay=0.75, mix=0.3)
mallet('Kalimba', ratio=2, pm=0.25, hit=0.08, decay=1.0).op(4, wave='noise', level=0.1, amp=perc(0.001, 0.02)).out(4, dry=0.6)

p = P(ORCH, 'Church Organ')
for k, (r, l) in enumerate([(1, 0.8), (2, 0.6), (3, 0.35), (4, 0.4), (6, 0.2), (8, 0.25)], start=1):
    p.op(k, ratio=r, level=l, vel=0.2, amp=adsr(0.04, 0.1, 1.0, 0.35))
p.carriers(1, 2, 3, 4, 5, 6, level=0.5).chorus(rate=0.25, depth=0.15, mix=0.2).reverb(size=0.95, decay=0.85, pre=30, mix=0.4)

p = P(ORCH, 'Accordion')
p.op(1, ratio=1, level=1, unison=2, detune=14, spread=0.6, vel=0.3, amp=adsr(0.03, 0.1, 1.0, 0.1))
p.op(2, ratio=1, level=0.7, amp=adsr(0.03, 0.1, 1.0, 0.1)).pm(2, 1, 0.48).fb(2, 0.2).op(3, ratio=2, level=0.4, amp=adsr(0.03, 0.1, 1.0, 0.1)).pm(3, 1, 0.2)
p.carriers(1, to='F1').flt(1, 'LP', cutoff=4000, key=0.3).lfo(1, 'sine', rate=6).mod('lfo1', 'op1Level', -0.15).reverb(size=0.5, decay=0.4, mix=0.15)

p = P(ORCH, 'Choir Aah')
p.op(1, ratio=1, level=1, unison=3, detune=9, spread=0.9, vel=0.3, amp=adsr(0.4, 0.3, 0.9, 0.5, t=0.2))
p.op(2, ratio=1, level=0.6, amp=adsr(0.4, 0.3, 0.9, 0.5)).pm(2, 1, 0.3).fb(2, 0.3)
p.carriers(1, to='F1').out(1, f2=0.8).flt(1, 'BP', cutoff=650, reso=0.55).flt(2, 'BP', cutoff=1100, reso=0.5)
vibrato(p, rate=5, delay=0.6, cents=0.08, ops=(1,)).chorus(rate=0.3, depth=0.3, mix=0.35).reverb(size=0.85, decay=0.7, mix=0.35)

# ------------------------------------------------------------ dubstep bass ----
def wob_core(p, saw=0.5, fb=0.3, sub=0.6, unison=2, detune=10, ratio3=2, pm3=0.2):
    """mono bass: saw-ish carrier (op 1 <- op 2 + feedback, op 3 one octave up), a sine sub on op 4"""
    p.mono(porta=0.04).bend(12)
    p.op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.5, vel=0.2, amp=adsr(0.004, 0.1, 1.0, 0.08))
    p.op(2, ratio=1, level=0.9, vel=0.2, amp=adsr(0.004, 0.1, 1.0, 0.08)).pm(2, 1, saw).fb(2, fb)
    p.op(3, ratio=ratio3, level=0.5, amp=adsr(0.004, 0.1, 1.0, 0.08)).pm(3, 1, pm3)
    p.op(4, ratio=0.5, level=sub, vel=0.1, amp=adsr(0.005, 0.1, 1.0, 0.1))
    p.carriers(1, to='F1').out(4, dry=0.8)
    return p

def wobble(name, div='1/4', lfo='sine', cutoff=320, reso=0.5, amt=0.45, slope=24, drive=0.35, dtype='soft', growl=0.0,
           ftype='LP', phase=0, key=0.2, extra=None, cat=DUB, pingpong=False):
    p = P(cat, name)
    wob_core(p)
    p.flt(1, ftype, cutoff=cutoff, reso=reso, slope=slope, drive=0.2, key=key)
    p.lfo(1, lfo, div=div, phase=phase).mod('lfo1', 'flt1Cutoff', amt)
    if growl: p.mod('lfo1', 'pm21', growl)
    p.mod('wheel', 'flt1Cutoff', 0.25)
    p.dist(dtype, drive=drive, tone=0.85, mix=0.7).eq(low=2, lowf=70, lowcut=30).comp(thresh=-14, ratio=4, attack=6, release=80)
    if extra: extra(p)
    return p

wobble('Wob 1/4 Classic', '1/4')
wobble('Wob 1/8 Saw', '1/8', amt=0.5)
wobble('Wob 1/8 Square', '1/8', lfo='square', amt=0.35, reso=0.4)
wobble('Wob 1/8T Triplet', '1/8T', lfo='tri', amt=0.48)
wobble('Wob 1/16 Fast', '1/16', amt=0.42, reso=0.55)
wobble('Wob 1/16T Shiver', '1/16T', lfo='tri', amt=0.4, reso=0.6)
wobble('Wob 1/4D Lazy', '1/4D', amt=0.5, cutoff=260)
wobble('Wob 1/2 Slow Roll', '1/2', amt=0.55, cutoff=240, reso=0.45)
wobble('Wob 1/8 Reso', '1/8', reso=0.78, amt=0.4, cutoff=260, drive=0.25)
wobble('Wob 1/8 Hard', '1/8', dtype='hard', drive=0.6, amt=0.45)
wobble('Wob 1/8 Fold', '1/8', dtype='fold', drive=0.4, amt=0.42, reso=0.4)
wobble('Wob 1/8 Crushed', '1/8', dtype='crush', drive=0.35, amt=0.4)
wobble('Wob Band-pass', '1/8', ftype='BP', cutoff=500, reso=0.6, amt=0.4, slope=12)
wobble('Wob High-pass Tear', '1/8', ftype='HP', cutoff=120, reso=0.5, amt=0.5, slope=24, drive=0.5, dtype='hard')
wobble('Wob 1/4 Growl', '1/4', amt=0.4, growl=0.3)
wobble('Wob 1/8 Growl', '1/8', amt=0.38, growl=0.35, drive=0.45)
wobble('Wob 1/16 Growl', '1/16', amt=0.35, growl=0.3, drive=0.4)
wobble('Wob Saw LFO Down', '1/8', lfo='saw', phase=180, amt=0.45)
wobble('Wob Saw LFO Up', '1/8', lfo='saw', amt=0.45)
wobble('Wob S&H Random', '1/16', lfo='sh', amt=0.4, reso=0.55)
wobble('Wob Ping-pong', '1/8', amt=0.45, extra=lambda p: p.delay(div='1/8', feedback=0.3, pingpong=True, tone=0.4, mix=0.18))
wobble('Wob Phased', '1/8', amt=0.4, extra=lambda p: p.phaser(rate=0.3, depth=0.6, stages=2, feedback=0.5, mix=0.4))
wobble('Wob Two LFO Poly', '1/8', amt=0.35, extra=lambda p: p.lfo(2, 'sine', div='1/4D').mod('lfo2', 'flt1Cutoff', 0.25))
wobble('Wob Key Tracked', '1/8', amt=0.45, key=0.6)
wobble('Wob Drawn Stutter', '1/8', lfo='drawn', amt=0.45,
       extra=lambda p: p.lfo(1, 'drawn', div='1/8', shape=[1] * 8 + [-1] * 8 + [1] * 8 + [-1] * 8 + [1] * 16 + [-1] * 16).mod('lfo1', 'flt1Cutoff', 0.45))

def growl(name, div='1/8', formant=(400, 1200), amt=(0.35, 0.3), pmamt=0.3, rm=0.0, drive=0.5, dtype='fold', fb=0.35, reso=0.6):
    p = P(DUB, name)
    wob_core(p, saw=0.45, fb=fb, unison=1)
    if rm: p.rm(3, 1, rm)
    p.out(1, f1=0.8, f2=0.8).flt(1, 'BP', cutoff=formant[0], reso=reso, slope=12, drive=0.2).flt(2, 'BP', cutoff=formant[1], reso=reso, slope=12, drive=0.2)
    p.lfo(1, 'sine', div=div).mod('lfo1', 'flt1Cutoff', amt[0]).mod('lfo1', 'flt2Cutoff', amt[1]).mod('lfo1', 'pm21', pmamt).mod('wheel', 'pm21', 0.2)
    p.dist(dtype, drive=drive, tone=0.8, mix=0.75).eq(low=3, lowf=60, lowcut=30, mid=2, midf=900).comp(thresh=-14, ratio=5, attack=5, release=70)
    return p
growl('Growl Talk 1/8', '1/8')
growl('Growl Talk 1/4', '1/4', formant=(350, 1000), amt=(0.4, 0.35))
growl('Growl Yoy', '1/8', formant=(500, 1500), amt=(0.45, -0.3), pmamt=0.2)
growl('Growl Metal', '1/8', rm=0.5, drive=0.6, dtype='hard', formant=(600, 2000))
growl('Growl Ring Snarl', '1/16', rm=0.7, pmamt=0.4, drive=0.5)
growl('Growl Deep Throat', '1/4D', formant=(250, 800), amt=(0.3, 0.45), fb=0.45, reso=0.7)
growl('Growl Robot Vowel', '1/8T', formant=(450, 1800), amt=(-0.3, 0.4), pmamt=0.15, dtype='crush', drive=0.3)
growl('Growl Screamer', '1/16', formant=(800, 2400), amt=(0.35, 0.35), pmamt=0.45, drive=0.65, dtype='hard')

p = P(DUB, 'Reese Wide')
p.mono(porta=0.05).op(1, ratio=1, level=1, unison=6, detune=22, spread=1.0, vel=0.2, amp=adsr(0.01, 0.1, 1, 0.1))
p.op(2, ratio=1, level=0.9, amp=adsr(0.01, 0.1, 1, 0.1)).pm(2, 1, 0.5).fb(2, 0.3).op(4, ratio=0.5, level=0.6, amp=adsr(0.01, 0.1, 1, 0.1))
p.carriers(1, to='F1').out(4, dry=0.8).flt(1, 'LP', cutoff=600, reso=0.2, slope=24).mod('wheel', 'flt1Cutoff', 0.4)
p.dist('soft', drive=0.4, tone=0.8, mix=0.6).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=8)

p = P(DUB, 'Reese Wob')
wob_core(p, unison=5, detune=20).flt(1, 'LP', cutoff=350, reso=0.4, slope=24).lfo(1, 'sine', div='1/4').mod('lfo1', 'flt1Cutoff', 0.45).mod('wheel', 'flt1Cutoff', 0.3)
p.dist('soft', drive=0.45, tone=0.8, mix=0.6).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=8)

p = P(DUB, 'Neuro Grind')
wob_core(p, saw=0.5, fb=0.45, unison=3, detune=15, ratio3=3, pm3=0.35).rm(3, 2, 0.4)
p.flt(1, 'BP', cutoff=700, reso=0.55, slope=12, drive=0.4).lfo(1, 'tri', div='1/16').mod('lfo1', 'flt1Cutoff', 0.3).lfo(2, 'sine', div='1/2').mod('lfo2', 'pm31', 0.3).mod('wheel', 'flt1Cutoff', 0.3)
p.phaser(rate=0.2, depth=0.8, stages=2, feedback=0.6, mix=0.5).dist('hard', drive=0.55, tone=0.75, mix=0.8).eq(low=3, lowf=60, lowcut=30, mid=3, midf=1500).comp(thresh=-16, ratio=6, attack=4)

p = P(DUB, 'Screech Bass')
p.mono(porta=0.03).op(1, ratio=1, level=1, vel=0.2, amp=adsr(0.004, 0.1, 1, 0.08)).op(2, ratio=1, level=0.9, amp=adsr(0.004, 0.1, 1, 0.08)).pm(2, 1, 0.55).fb(2, 0.5)
p.op(3, ratio=7, level=0.6, amp=adsr(0.004, 0.1, 1, 0.08)).pm(3, 2, 0.4).op(4, ratio=0.5, level=0.5, amp=adsr(0.005, 0.1, 1, 0.1))
p.carriers(1, to='F1').out(4, dry=0.8).flt(1, 'LP', cutoff=1200, reso=0.75, slope=12).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.4).mod('lfo1', 'pm32', 0.25).mod('wheel', 'pm32', 0.3)
p.dist('hard', drive=0.6, tone=0.9, mix=0.8).eq(low=2, lowf=60, lowcut=30, high=2, highf=4000).comp(thresh=-16, ratio=6, attack=4)

p = P(DUB, 'Laser Bass')
wob_core(p, saw=0.4, ratio3=5, pm3=0.3).flt(1, 'LP', cutoff=500, reso=0.65, slope=24)
p.op(3, pitch=pitch_drop(1.0, 0.12), pitchamt=24).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.4).mod('lfo1', 'pm31', 0.25)
p.dist('soft', drive=0.4, tone=0.9, mix=0.7).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)

p = P(DUB, 'Sub + Wob Split')
wob_core(p, sub=0.9).flt(1, 'LP', cutoff=400, reso=0.5, slope=24).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.45)
p.op(4, level=0.9).out(4, dry=1.0).out(1, f1=0.6).dist('soft', drive=0.3, tone=0.8, mix=0.5).eq(low=1, lowf=50, lowcut=25).comp(thresh=-12, ratio=4, attack=8)

p = P(DUB, 'Wub Trip Gate')
wob_core(p).flt(1, 'LP', cutoff=500, reso=0.45, slope=24).lfo(1, 'square', div='1/8T').mod('lfo1', 'op1Level', -0.5).mod('lfo1', 'op3Level', -0.5)
p.lfo(2, 'sine', div='1/2').mod('lfo2', 'flt1Cutoff', 0.35).dist('soft', drive=0.35, tone=0.85, mix=0.6).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=5)

p = P(DUB, 'Tearout Rip')
wob_core(p, saw=0.55, fb=0.5, unison=2, detune=18, ratio3=2, pm3=0.35).flt(1, 'HP', cutoff=150, reso=0.5, slope=24, drive=0.5)
p.lfo(1, 'tri', div='1/8').mod('lfo1', 'flt1Cutoff', 0.55).mod('lfo1', 'pm21', 0.35).rm(2, 1, 0.3)
p.dist('hard', drive=0.7, tone=0.8, mix=0.85).eq(low=3, lowf=70, lowcut=35, mid=3, midf=2500, q=0.8).comp(thresh=-18, ratio=8, attack=3, release=60)

p = P(DUB, 'Brostep Yell')
wob_core(p, saw=0.5, fb=0.4, ratio3=3, pm3=0.3).out(1, f1=0.8, f2=0.8).flt(1, 'BP', cutoff=700, reso=0.6).flt(2, 'BP', cutoff=2200, reso=0.55)
p.lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.45).mod('lfo1', 'flt2Cutoff', 0.35).lfo(2, 'square', div='1/4').mod('lfo2', 'pm31', 0.25).mod('wheel', 'flt2Cutoff', 0.3)
p.dist('fold', drive=0.5, tone=0.85, mix=0.8).eq(low=3, lowf=60, lowcut=30).comp(thresh=-16, ratio=6, attack=4)

p = P(DUB, 'Dirty Wob Octaves')
wob_core(p, ratio3=2, pm3=0.4).op(5, ratio=2, level=0.5, amp=adsr(0.004, 0.1, 1, 0.08)).out(5, f1=0.7).flt(1, 'LP', cutoff=380, reso=0.5, slope=24)
p.lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.45).dist('crush', drive=0.45, tone=0.7, mix=0.6).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=5, attack=5)

p = P(DUB, 'Clean Wob Sine')
p.mono(porta=0.04).op(1, ratio=1, level=1, amp=adsr(0.004, 0.1, 1, 0.08)).op(2, ratio=1, level=0.7, amp=adsr(0.004, 0.1, 1, 0.08)).pm(2, 1, 0.3)
p.op(4, ratio=0.5, level=0.7, amp=adsr(0.005, 0.1, 1, 0.1)).carriers(1, to='F1').out(4, dry=0.8).flt(1, 'LP', cutoff=600, reso=0.3, slope=12)
p.lfo(1, 'sine', div='1/4').mod('lfo1', 'pm21', 0.3).mod('lfo1', 'flt1Cutoff', 0.3).eq(low=2, lowf=60).comp(thresh=-12, ratio=3, attack=8)

p = P(DUB, 'Hoover Bass')
p.mono(porta=0.08).op(1, ratio=1, level=1, unison=6, detune=30, spread=0.8, vel=0.2, amp=adsr(0.02, 0.1, 1, 0.15), pitch=pitch_drop(0.25, 0.4), pitchamt=12)
p.op(2, ratio=1, level=0.9, amp=adsr(0.02, 0.1, 1, 0.15), pitch=pitch_drop(0.25, 0.4), pitchamt=12).pm(2, 1, 0.5).fb(2, 0.35)
p.op(4, ratio=0.5, level=0.5, amp=adsr(0.01, 0.1, 1, 0.1)).carriers(1, to='F1').out(4, dry=0.7).flt(1, 'LP', cutoff=2500, reso=0.2, slope=12)
p.lfo(1, 'sine', div='1/4').mod('lfo1', 'flt1Cutoff', 0.2).chorus(rate=0.5, depth=0.4, mix=0.4).dist('soft', drive=0.3, mix=0.5).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=8)

p = P(DUB, 'Wob Formant Sweep')
wob_core(p, unison=1).out(1, f1=0.9).flt(1, 'BP', cutoff=300, reso=0.7, slope=12).lfo(1, 'sine', div='1/4').mod('lfo1', 'flt1Cutoff', 0.6).mod('wheel', 'flt1Cutoff', 0.3)
p.dist('soft', drive=0.4, tone=0.8, mix=0.6).eq(low=3, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)

p = P(DUB, 'Wob Pitch Bend')
wob_core(p).flt(1, 'LP', cutoff=400, reso=0.5, slope=24).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.4).mod('lfo1', 'op1Fine', 0.12).mod('lfo1', 'op2Fine', 0.12)
p.dist('soft', drive=0.35, tone=0.85, mix=0.6).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)

p = P(DUB, 'Wob Octave Jump')
wob_core(p).flt(1, 'LP', cutoff=450, reso=0.5, slope=24).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.4)
p.lfo(2, 'square', div='1/2').mod('lfo2', 'op3Level', 0.5).mod('lfo2', 'pm31', 0.2).dist('soft', drive=0.4, tone=0.85, mix=0.65).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)

p = P(DUB, 'Growl Pad Bass')
wob_core(p, unison=3, detune=12).flt(1, 'LP', cutoff=500, reso=0.4, slope=24).op(1, amp=adsr(0.15, 0.2, 1, 0.3)).op(2, amp=adsr(0.15, 0.2, 1, 0.3)).op(3, amp=adsr(0.15, 0.2, 1, 0.3))
p.lfo(1, 'sine', div='1/2').mod('lfo1', 'flt1Cutoff', 0.4).mod('lfo1', 'pm21', 0.2).chorus(rate=0.3, depth=0.3, mix=0.3).dist('soft', drive=0.3, mix=0.5).reverb(size=0.5, decay=0.4, mix=0.15).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=8)

p = P(DUB, 'Riddim Square')
p.mono(porta=0.02).op(1, partials=[1, 0, 0.33, 0, 0.2, 0, 0.14, 0, 0.11, 0, 0.09], level=1, amp=adsr(0.003, 0.08, 1, 0.05))
p.op(2, ratio=1, level=0.8, amp=adsr(0.003, 0.08, 1, 0.05)).pm(2, 1, 0.35).op(4, ratio=0.5, level=0.7, amp=adsr(0.003, 0.1, 1, 0.06)).carriers(1, to='F1').out(4, dry=0.8)
p.flt(1, 'LP', cutoff=500, reso=0.6, slope=24).lfo(1, 'square', div='1/16').mod('lfo1', 'flt1Cutoff', 0.35).mod('lfo1', 'pm21', 0.25)
p.dist('hard', drive=0.5, tone=0.85, mix=0.8).eq(low=3, lowf=60, lowcut=30, mid=2, midf=1200).comp(thresh=-16, ratio=6, attack=3)

p = P(DUB, 'Wob Drop Siren')
wob_core(p).op(1, pitch=env([[0, 0.5], [2, 0.5], [6, 0.25, 0.2], [7, 0.25]], sustain=3, sync=True), pitchamt=24)
p.op(2, pitch=env([[0, 0.5], [2, 0.5], [6, 0.25, 0.2], [7, 0.25]], sustain=3, sync=True), pitchamt=24)
p.flt(1, 'LP', cutoff=450, reso=0.5, slope=24).lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.45).dist('soft', drive=0.4, tone=0.85, mix=0.65).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=6)

# -------------------------------------------------------------------- bass ----
def sub(name, drive=0.0, decay=None, harmonic=0.0, pitch=None):
    p = P(BASS, name)
    a = adsr(0.005, 0.1, 1, 0.12) if decay is None else perc(0.003, decay)
    p.op(1, ratio=1, level=1, vel=0.3, amp=a, pitch=pitch, pitchamt=36 if pitch else None)
    if harmonic: p.op(2, ratio=1, level=0.6, amp=a).pm(2, 1, harmonic)
    p.mono(porta=0.03).carriers(1).eq(low=1, lowf=50, lowcut=25).comp(thresh=-10, ratio=3, attack=10)
    if drive: p.dist('soft', drive=drive, tone=0.4, mix=0.6)
    return p
sub('Sub Sine')
sub('808 Sub', decay=1.8, drive=0.25, pitch=pitch_drop(0.8, 0.06))
sub('808 Distorted', decay=1.6, drive=0.6, harmonic=0.3, pitch=pitch_drop(0.85, 0.05)).eq(mid=3, midf=120, q=1.5)
sub('Sub Harmonic', harmonic=0.25, drive=0.15)

p = P(BASS, 'Reese Classic')
p.mono(porta=0.05).op(1, ratio=1, level=1, unison=2, detune=24, spread=0.7, amp=adsr(0.01, 0.1, 1, 0.12)).op(2, ratio=1, level=0.85, amp=adsr(0.01, 0.1, 1, 0.12)).pm(2, 1, 0.5).fb(2, 0.3)
p.carriers(1, to='F1').flt(1, 'LP', cutoff=800, reso=0.15, slope=24).mod('wheel', 'flt1Cutoff', 0.4).eq(low=2, lowf=60, lowcut=30).comp(thresh=-12, ratio=4, attack=8)

p = P(BASS, 'Acid Squelch')
p.mono(porta=0.04).op(1, ratio=1, level=1, amp=adsr(0.003, 0.2, 0.7, 0.1)).op(2, ratio=1, level=0.9, amp=adsr(0.003, 0.2, 0.7, 0.1)).pm(2, 1, 0.52).fb(2, 0.3)
p.carriers(1, to='F1').flt(1, 'LP', cutoff=300, reso=0.8, slope=24, env=0.55, vel=0.3, cut=perc(0.001, 0.25)).mod('wheel', 'flt1Cutoff', 0.4)
p.dist('soft', drive=0.3, tone=0.9, mix=0.5).delay(div='1/8D', feedback=0.3, pingpong=True, tone=0.5, mix=0.15).eq(low=2, lowf=70, lowcut=35).comp(thresh=-12, ratio=4, attack=6)

p = P(BASS, 'FM Slap')
p.op(1, ratio=1, level=1, vel=0.6, amp=adsr(0.002, 0.4, 0.5, 0.1, t=-0.6)).op(2, ratio=1, level=0.9, vel=0.9, amp=perc(0.002, 0.25)).pm(2, 1, 0.55)
p.op(3, ratio=4, level=0.5, vel=1, amp=perc(0.001, 0.06)).pm(3, 1, 0.3).carriers(1).mono(porta=0.02).eq(low=2, lowf=80, mid=2, midf=2500).comp(thresh=-14, ratio=4, attack=3)

p = P(BASS, 'Moog Ladder')
p.mono(porta=0.06).op(1, ratio=1, level=1, amp=adsr(0.004, 0.3, 0.8, 0.12)).op(2, ratio=1, level=0.9, amp=adsr(0.004, 0.3, 0.8, 0.12)).pm(2, 1, 0.5).fb(2, 0.3)
p.op(3, ratio=0.5, level=0.6, amp=adsr(0.004, 0.3, 0.8, 0.12)).pm(2, 3, 0.2).carriers(1, 3, level=0.9, to='F1').flt(1, 'LP', cutoff=450, reso=0.45, slope=24, env=0.4, vel=0.25, key=0.3, cut=perc(0.002, 0.3)).eq(low=2, lowf=70, lowcut=30).comp(thresh=-12, ratio=4, attack=8)

p = P(BASS, 'Square Bass')
p.mono(porta=0.03).op(1, partials=[1, 0, 0.33, 0, 0.2, 0, 0.14, 0, 0.11], level=1, amp=adsr(0.004, 0.2, 0.9, 0.1)).op(2, ratio=0.5, level=0.5, amp=adsr(0.004, 0.2, 0.9, 0.1))
p.carriers(1, 2, level=0.9, to='F1').flt(1, 'LP', cutoff=900, reso=0.3, slope=24, env=0.3, cut=perc(0.002, 0.3)).eq(low=2, lowf=70, lowcut=30).comp(thresh=-12, ratio=4, attack=8)

p = P(BASS, 'Donk')
p.mono().op(1, ratio=1, level=1, amp=perc(0.001, 0.35), pitch=pitch_drop(0.75, 0.05), pitchamt=12).op(2, ratio=1, level=0.8, amp=perc(0.001, 0.12)).pm(2, 1, 0.45)
p.carriers(1).dist('soft', drive=0.3, mix=0.5).eq(low=1, lowf=90, mid=3, midf=400).comp(thresh=-12, ratio=4, attack=3)

p = P(BASS, 'Pluck Bass')
p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.002, 0.6, 0.0, 0.1, t=-0.6)).op(2, ratio=1, level=0.9, vel=0.9, amp=perc(0.002, 0.3)).pm(2, 1, 0.5)
p.op(3, ratio=0.5, level=0.6, amp=adsr(0.002, 0.8, 0.0, 0.1)).carriers(1, 3, level=0.9, to='F1').flt(1, 'LP', cutoff=600, reso=0.3, slope=24, env=0.4, cut=perc(0.001, 0.3)).eq(low=2, lowf=70, lowcut=30).comp(thresh=-12, ratio=4, attack=5)

p = P(BASS, 'Deep House Bass')
p.mono(porta=0.03).op(1, ratio=1, level=1, amp=adsr(0.005, 0.3, 0.6, 0.15)).op(2, ratio=2, level=0.5, amp=perc(0.005, 0.4)).pm(2, 1, 0.3).op(3, ratio=0.5, level=0.6, amp=adsr(0.005, 0.3, 0.7, 0.15))
p.carriers(1, 3, level=0.9, to='F1').flt(1, 'LP', cutoff=500, reso=0.25, slope=24, env=0.3, cut=perc(0.002, 0.4)).eq(low=2, lowf=60, lowcut=30).comp(thresh=-12, ratio=4, attack=8)

p = P(BASS, 'Trap 808 Long')
p.mono(porta=0.08).op(1, ratio=1, level=1, amp=env([[0, 0], [0.003, 1], [2.5, 0.4, -0.5], [3.0, 0, -0.5]], sustain=2), pitch=pitch_drop(0.8, 0.05), pitchamt=36)
p.op(2, ratio=1, level=0.5, amp=perc(0.003, 1.0)).pm(2, 1, 0.25).carriers(1).dist('soft', drive=0.4, tone=0.5, mix=0.6).eq(low=2, lowf=45, lowcut=25, mid=2, midf=90, q=1.2).comp(thresh=-10, ratio=4, attack=10, limit=True)

p = P(BASS, 'Garage Bass')
p.mono(porta=0.02).op(1, ratio=1, level=1, amp=adsr(0.003, 0.3, 0.5, 0.08)).op(2, ratio=1, level=0.85, amp=adsr(0.003, 0.3, 0.5, 0.08)).pm(2, 1, 0.45).fb(2, 0.2)
p.op(3, ratio=0.5, level=0.7, amp=adsr(0.003, 0.3, 0.6, 0.08)).carriers(1, 3, level=0.9, to='F1').flt(1, 'LP', cutoff=700, reso=0.4, slope=24, env=0.35, cut=perc(0.002, 0.2)).eq(low=2, lowf=60, lowcut=30).comp(thresh=-12, ratio=4, attack=5)

p = P(BASS, 'DnB Reese Dark')
p.mono(porta=0.05).op(1, ratio=1, level=1, unison=3, detune=28, spread=0.5, amp=adsr(0.01, 0.1, 1, 0.12)).op(2, ratio=1, level=0.9, amp=adsr(0.01, 0.1, 1, 0.12)).pm(2, 1, 0.48).fb(2, 0.35)
p.op(4, ratio=0.5, level=0.6, amp=adsr(0.01, 0.1, 1, 0.1)).carriers(1, to='F1').out(4, dry=0.8).flt(1, 'LP', cutoff=380, reso=0.3, slope=24).mod('wheel', 'flt1Cutoff', 0.4)
p.dist('soft', drive=0.35, tone=0.7, mix=0.5).eq(low=2, lowf=55, lowcut=28).comp(thresh=-14, ratio=5, attack=8)

p = P(BASS, 'Techno Rumble')
p.mono(porta=0.03).op(1, ratio=1, level=1, amp=adsr(0.005, 0.4, 0.5, 0.2)).op(2, ratio=1, level=0.7, amp=perc(0.005, 0.3)).pm(2, 1, 0.3).fb(2, 0.4)
p.carriers(1, to='F1').flt(1, 'LP', cutoff=180, reso=0.4, slope=24).dist('soft', drive=0.5, tone=0.3, mix=0.7).reverb(size=0.6, decay=0.5, damp=0.8, mix=0.25).eq(low=3, lowf=50, lowcut=25).comp(thresh=-12, ratio=6, attack=10)

p = P(BASS, 'Funk FM Bass')
p.op(1, ratio=1, level=1, vel=0.6, amp=adsr(0.002, 0.5, 0.3, 0.1, t=-0.6)).op(2, ratio=1, level=0.9, vel=1.0, amp=perc(0.002, 0.18)).pm(2, 1, 0.5)
p.op(3, ratio=2, level=0.5, vel=1.0, amp=perc(0.001, 0.1)).pm(3, 1, 0.25).carriers(1).mono(porta=0.015).eq(low=2, lowf=80, mid=2, midf=1800).comp(thresh=-14, ratio=4, attack=3)

p = P(BASS, 'Organ Bass')
p.op(1, ratio=1, level=1, amp=adsr(0.01, 0.1, 1, 0.08)).op(2, ratio=2, level=0.5, amp=adsr(0.01, 0.1, 1, 0.08)).op(3, ratio=0.5, level=0.7, amp=adsr(0.01, 0.1, 1, 0.08))
p.carriers(1, 2, 3, level=0.8).mono(porta=0.02).dist('soft', drive=0.2, mix=0.4).eq(low=2, lowf=70, lowcut=30).comp(thresh=-12, ratio=3, attack=8)

p = P(BASS, 'Sync Lead Bass')
p.mono(porta=0.04).op(1, ratio=1, level=1, amp=adsr(0.004, 0.2, 0.8, 0.1)).op(2, ratio=3, level=0.9, amp=adsr(0.004, 0.2, 0.8, 0.1), mod=env([[0, 1], [0.3, 0.5, -0.5], [1, 0.5]], sustain=2), modamt=0.8).pm(2, 1, 0.45).fb(2, 0.3)
p.op(4, ratio=0.5, level=0.6, amp=adsr(0.004, 0.2, 0.9, 0.1)).carriers(1, to='F1').out(4, dry=0.8).flt(1, 'LP', cutoff=1500, reso=0.3, slope=12).dist('hard', drive=0.4, mix=0.6).eq(low=2, lowf=60, lowcut=30).comp(thresh=-14, ratio=4, attack=5)

p = P(BASS, 'Wobble Lite 1/4')
wob_core(p).p['voiceMode'] = 0
p.flt(1, 'LP', cutoff=600, reso=0.3, slope=12).lfo(1, 'sine', div='1/4').mod('lfo1', 'flt1Cutoff', 0.3).eq(low=2, lowf=60, lowcut=30).comp(thresh=-12, ratio=3, attack=8)
PRESETS[-1].cat = BASS

# ------------------------------------------------------------------- leads ----
def lead(name, pm=0.5, fb=0.25, unison=1, detune=10, ratio3=None, pm3=0.2, cutoff=4000, reso=0.15, attack=0.01, porta=0.05,
         legato_=True, vib=0.1, drive=0.0, delay=True, extra=None):
    p = P(LEAD, name)
    a = adsr(attack, 0.2, 0.85, 0.15)
    p.op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.7, vel=0.3, amp=a)
    p.op(2, ratio=1, level=0.85, vel=0.5, amp=a).pm(2, 1, pm).fb(2, fb)
    if ratio3: p.op(3, ratio=ratio3, level=0.5, amp=a).pm(3, 1, pm3)
    p.carriers(1, to='F1').flt(1, 'LP', cutoff=cutoff, reso=reso, key=0.4, vel=0.3, env=0.2, cut=adsr(0.005, 0.4, 0.5, 0.2))
    if legato_: p.legato(porta)
    if vib: vibrato(p, rate=5.5, delay=0.4, cents=vib, ops=(1, 2))
    if drive: p.dist('soft', drive=drive, tone=0.85, mix=0.6)
    if delay: p.delay(div='1/8D', feedback=0.3, pingpong=True, tone=0.5, mix=0.18)
    p.reverb(size=0.5, decay=0.45, mix=0.14).comp(thresh=-14, ratio=3, attack=8)
    if extra: extra(p)
    return p
lead('Supersaw Lead', unison=8, detune=18, pm=0.5, fb=0.3, cutoff=6000, legato_=False, vib=0.0, extra=lambda p: p.chorus(rate=0.4, depth=0.3, mix=0.3))
lead('Trance Lead', unison=4, detune=14, ratio3=2, cutoff=5000, legato_=False, extra=lambda p: p.chorus(rate=0.5, depth=0.25, mix=0.25))
lead('Hoover Lead', unison=6, detune=32, pm=0.5, fb=0.35, cutoff=3500, legato_=False, vib=0.0,
     extra=lambda p: p.op(1, pitch=pitch_drop(0.2, 0.5), pitchamt=12).op(2, pitch=pitch_drop(0.2, 0.5), pitchamt=12).chorus(rate=0.6, depth=0.4, mix=0.4))
lead('Square Lead', pm=0.0, extra=lambda p: p.op(1, partials=[1, 0, 0.33, 0, 0.2, 0, 0.14, 0, 0.11, 0, 0.09, 0, 0.08]))
lead('Sync Lead', pm=0.45, fb=0.35, ratio3=4, pm3=0.3, extra=lambda p: p.op(3, mod=env([[0, 1], [0.4, 0.5, -0.5], [1, 0.5]], sustain=2), modamt=0.9))
lead('Dubstep Screech Lead', pm=0.55, fb=0.5, ratio3=7, pm3=0.35, cutoff=2500, reso=0.6, drive=0.5,
     extra=lambda p: p.lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.4).mod('lfo1', 'pm31', 0.25))
lead('Growl Lead', pm=0.5, fb=0.4, ratio3=2, pm3=0.3, cutoff=1500, reso=0.5, drive=0.45,
     extra=lambda p: p.lfo(1, 'tri', div='1/16').mod('lfo1', 'pm21', 0.3).mod('lfo1', 'flt1Cutoff', 0.3))
lead('Talkbox Lead', pm=0.45, cutoff=900, reso=0.65, extra=lambda p: p.out(1, f2=0.8).flt(2, 'BP', cutoff=1800, reso=0.6).mod('wheel', 'flt1Cutoff', 0.5).mod('wheel', 'flt2Cutoff', -0.3))
lead('Brass Lead', pm=0.5, fb=0.2, ratio3=2, attack=0.04, cutoff=3500, extra=lambda p: p.op(2, mod=swell(0.15, 0.3, 0.6)))
lead('Sine Lead', pm=0.08, cutoff=8000, vib=0.12, delay=True)
lead('Whistle Lead', pm=0.05, ratio3=3, pm3=0.05, cutoff=9000, vib=0.15, extra=lambda p: p.op(1, ratio=2).op(2, ratio=2))
lead('Portamento Glide', pm=0.4, porta=0.18, vib=0.08)
lead('Acid Lead', pm=0.5, fb=0.3, cutoff=800, reso=0.75, drive=0.3, extra=lambda p: p.flt(1, env=0.5, cut=perc(0.001, 0.3)).mod('wheel', 'flt1Cutoff', 0.4))
lead('Neuro Lead', pm=0.5, fb=0.45, ratio3=3, pm3=0.3, cutoff=2000, reso=0.4, drive=0.5,
     extra=lambda p: p.rm(3, 1, 0.3).phaser(rate=0.25, depth=0.7, stages=2, feedback=0.5, mix=0.4).lfo(1, 'sine', div='1/4').mod('lfo1', 'pm21', 0.2))
lead('Bell Lead', pm=0.35, ratio3=3.5, pm3=0.3, cutoff=8000, legato_=False, vib=0.0, attack=0.002,
     extra=lambda p: p.op(1, amp=adsr(0.002, 2.0, 0.3, 0.4, t=-0.6)).op(3, amp=perc(0.002, 1.2)))
lead('Distorted Lead', pm=0.5, fb=0.35, ratio3=2, drive=0.7, cutoff=3000, extra=lambda p: p.dist('hard', drive=0.6, tone=0.8, mix=0.8))
lead('Vocal Lead', pm=0.4, cutoff=700, reso=0.6, extra=lambda p: p.out(1, f2=0.9).flt(2, 'BP', cutoff=2400, reso=0.55).lfo(3, 'sine', rate=0.5).mod('lfo3', 'flt1Cutoff', 0.2).mod('lfo3', 'flt2Cutoff', -0.15))
lead('Chip Lead', pm=0.0, vib=0.15, delay=False, extra=lambda p: p.op(1, partials=[1, 0, 0.33, 0, 0.2, 0, 0.14, 0, 0.11]).flt(1, cutoff=9000).op(1, amp=adsr(0.001, 0.05, 1, 0.02)).op(2, amp=adsr(0.001, 0.05, 1, 0.02)))
lead('Riff Lead', pm=0.5, fb=0.25, ratio3=2, pm3=0.25, cutoff=3000, drive=0.3, porta=0.03, extra=lambda p: p.mod('vel', 'flt1Cutoff', 0.3))
lead('303 Lead', pm=0.5, fb=0.3, cutoff=600, reso=0.8, porta=0.04, extra=lambda p: p.flt(1, env=0.6, cut=perc(0.001, 0.22)).mod('wheel', 'flt1Cutoff', 0.5).delay(div='1/16', feedback=0.4, pingpong=True, tone=0.4, mix=0.2))
lead('Lo-fi Lead', pm=0.4, cutoff=3000, drive=0.4, extra=lambda p: p.dist('crush', drive=0.35, tone=0.6, mix=0.7))
lead('FM Bright Lead', pm=0.6, fb=0.3, ratio3=3, pm3=0.3, cutoff=8000, legato_=False)
lead('Wobble Lead', pm=0.45, fb=0.3, ratio3=2, pm3=0.25, cutoff=2000, reso=0.5, extra=lambda p: p.lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.45))
lead('Fifths Lead', pm=0.45, ratio3=1.5, pm3=0.0, cutoff=4500, extra=lambda p: p.out(3, f1=0.8).op(3, level=0.8))

# ------------------------------------------------------------------- pads -----
def pad(name, pm=0.3, fb=0.2, unison=4, detune=12, attack=0.8, release=1.2, cutoff=2500, ratio3=None, pm3=0.15, extra=None, cat=PAD):
    p = P(cat, name)
    a = adsr(attack, 0.5, 0.9, release, t=0.2)
    p.op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.9, vel=0.3, amp=a)
    p.op(2, ratio=1, level=0.7, vel=0.4, amp=a).pm(2, 1, pm).fb(2, fb)
    if ratio3: p.op(3, ratio=ratio3, level=0.5, unison=2, detune=8, spread=0.8, amp=a).pm(2, 3, pm3).out(3, f1=0.7)
    p.carriers(1, to='F1').flt(1, 'LP', cutoff=cutoff, key=0.3, vel=0.2, env=0.3, cut=env([[0, 0], [2.5, 1, 0.2], [5, 0.5, -0.3], [6, 0, -0.5]], sustain=2))
    p.lfo(1, 'sine', rate=0.15).mod('lfo1', 'flt1Cutoff', 0.12).mod('wheel', 'flt1Cutoff', 0.3)
    p.chorus(rate=0.3, depth=0.35, mix=0.35).reverb(size=0.8, decay=0.7, pre=20, mix=0.3)
    if extra: extra(p)
    return p
pad('Warm Pad')
pad('Glass Pad', pm=0.2, ratio3=4, pm3=0.25, cutoff=5000, extra=lambda p: p.op(3, level=0.35, amp=adsr(1.5, 0.5, 0.8, 1.5)))
pad('Dark Pad', pm=0.35, fb=0.3, cutoff=900, attack=1.2, extra=lambda p: p.eq(low=2, lowf=120))
pad('Evolving Pad', pm=0.3, ratio3=2, extra=lambda p: p.lfo(2, 'tri', rate=0.07).mod('lfo2', 'pm21', 0.2).mod('lfo2', 'op3Level', 0.3).lfo(3, 'sine', rate=0.11).mod('lfo3', 'op1Pan', 0.4))
pad('Choir Pad', pm=0.25, cutoff=700, extra=lambda p: p.flt(1, 'BP', reso=0.5).out(1, f2=0.8).flt(2, 'BP', cutoff=1200, reso=0.5))
pad('Strings Pad', pm=0.42, fb=0.25, ratio3=3, pm3=0.1, cutoff=3500, attack=0.5)
pad('Shimmer Pad', pm=0.25, ratio3=2, pm3=0.3, cutoff=6000, extra=lambda p: p.reverb(size=0.98, decay=0.92, pre=40, mix=0.5).delay(div='1/4D', feedback=0.45, pingpong=True, tone=0.7, mix=0.25))
pad('Drone', pm=0.3, fb=0.5, unison=6, detune=6, attack=2.5, release=3, cutoff=1200, extra=lambda p: p.lfo(2, 'tri', rate=0.05).mod('lfo2', 'flt1Cutoff', 0.25).mod('lfo2', 'pm22', 0.2))
pad('Dubstep Atmos', pm=0.3, cutoff=1500, extra=lambda p: p.lfo(2, 'sine', div='1/2').mod('lfo2', 'flt1Cutoff', 0.2).lfo(3, 'sine', div='1/8').mod('lfo3', 'op1Level', -0.2).eq(low=2, lowf=80))
pad('Cinematic Swell', pm=0.4, unison=5, detune=10, attack=3.0, release=2.5, cutoff=2500, extra=lambda p: p.flt(1, cut=env([[0, 0], [3.5, 1, 0.3], [5, 1]], sustain=2), env=0.5).reverb(size=0.95, decay=0.85, mix=0.4))
pad('Noise Wash', pm=0.2, cutoff=1500, extra=lambda p: p.op(4, wave='noise', level=0.25, amp=adsr(1.5, 0.5, 0.8, 2.0)).out(4, f2=1).flt(2, 'BP', cutoff=1800, reso=0.3).lfo(2, 'sine', rate=0.08).mod('lfo2', 'flt2Cutoff', 0.35))
pad('Vocal Pad', pm=0.3, cutoff=600, extra=lambda p: p.flt(1, 'BP', reso=0.55).out(1, f2=0.9).flt(2, 'BP', cutoff=1900, reso=0.5).lfo(2, 'sine', rate=0.2).mod('lfo2', 'flt1Cutoff', 0.25).mod('lfo2', 'flt2Cutoff', -0.2))
pad('Sweep Pad', pm=0.35, cutoff=800, extra=lambda p: p.lfo(2, 'tri', div='1/1').mod('lfo2', 'flt1Cutoff', 0.5).flt(1, reso=0.45))
pad('Crystal Pad', pm=0.15, ratio3=6, pm3=0.3, cutoff=9000, attack=0.4, extra=lambda p: p.op(3, amp=adsr(0.3, 1.5, 0.3, 1.5)).delay(div='1/8', feedback=0.4, pingpong=True, tone=0.8, mix=0.25))
pad('Hollow Pad', pm=0.0, cutoff=3000, extra=lambda p: p.op(1, partials=[1, 0, 0.33, 0, 0.2]).op(2, level=0.0))
pad('Brass Pad', pm=0.45, fb=0.2, ratio3=2, pm3=0.2, cutoff=2800, attack=0.3, extra=lambda p: p.op(2, mod=swell(0.5, 0.3, 0.6)))
pad('Space Pad', pm=0.25, ratio3=0.5, pm3=0.1, cutoff=2000, attack=1.5, extra=lambda p: p.phaser(rate=0.08, depth=0.8, stages=2, feedback=0.4, mix=0.4).reverb(size=0.95, decay=0.9, mix=0.45))
pad('Fifths Pad', pm=0.3, ratio3=1.5, pm3=0.0, cutoff=3000, extra=lambda p: p.op(3, level=0.7))
pad('Ambient Bells Pad', pm=0.2, ratio3=3.5, pm3=0.35, cutoff=7000, attack=0.6, extra=lambda p: p.op(3, amp=adsr(0.002, 3, 0.2, 2, t=-0.6), level=0.4).reverb(size=0.9, decay=0.85, mix=0.4))
pad('Granular Shimmer', pm=0.25, cutoff=4000, extra=lambda p: p.lfo(2, 'sh', div='1/16').mod('lfo2', 'op1Fine', 0.25).mod('lfo2', 'op1Pan', 0.6).delay(div='1/16', feedback=0.6, pingpong=True, tone=0.7, mix=0.35))

# ----------------------------------------------------------------- plucks -----
def pluck(name, pm=0.45, ratio2=1, decay=0.5, hold=0.0, ratio3=None, pm3=0.2, cutoff=5000, env_=0.4, delay=True, extra=None, cat=PLUCK):
    p = P(cat, name)
    p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.002, decay, hold, 0.15, t=-0.6))
    p.op(2, ratio=ratio2, level=0.8, vel=0.9, amp=perc(0.002, decay * 0.5)).pm(2, 1, pm)
    if ratio3: p.op(3, ratio=ratio3, level=0.4, vel=0.9, amp=perc(0.001, decay * 0.25)).pm(3, 1, pm3)
    p.carriers(1, to='F1').flt(1, 'LP', cutoff=cutoff, key=0.4, vel=0.3, env=env_, cut=perc(0.001, decay * 0.6))
    if delay: p.delay(div='1/8D', feedback=0.35, pingpong=True, tone=0.6, mix=0.22)
    p.reverb(size=0.5, decay=0.45, mix=0.18)
    if extra: extra(p)
    return p
pluck('FM Pluck')
pluck('Trance Pluck', pm=0.5, decay=0.35, cutoff=3000, env_=0.5, extra=lambda p: p.op(1, unison=3, detune=10, spread=0.8))
pluck('Dub Pluck', pm=0.4, decay=0.3, cutoff=2000, extra=lambda p: p.delay(div='1/4D', feedback=0.55, pingpong=True, tone=0.35, mix=0.35))
pluck('Arp Saw', pm=0.5, decay=0.25, hold=0.2, cutoff=4000, delay=False, extra=lambda p: p.fb(2, 0.3).delay(div='1/16', feedback=0.3, pingpong=True, tone=0.6, mix=0.2))
pluck('Arp Square', pm=0.0, decay=0.25, hold=0.3, delay=False, extra=lambda p: p.op(1, partials=[1, 0, 0.33, 0, 0.2, 0, 0.14]).delay(div='1/8', feedback=0.35, pingpong=True, mix=0.2))
pluck('Stab Pluck', pm=0.55, ratio3=2, pm3=0.3, decay=0.3, cutoff=6000)
pluck('Marimba Pluck', pm=0.3, ratio2=4, decay=0.6, cutoff=8000, env_=0.0, delay=False)
pluck('Bell Pluck', pm=0.35, ratio2=3.5, decay=1.5, ratio3=7, pm3=0.15, cutoff=9000, env_=0.0)
pluck('Pizzi Synth', pm=0.4, ratio3=3, pm3=0.15, decay=0.35, cutoff=3000)
pluck('Water Drop', pm=0.3, ratio2=2, decay=0.5, cutoff=7000, env_=0.0, extra=lambda p: p.op(1, pitch=pitch_drop(0.0, 0.08, t=0.3), pitchamt=24))
pluck('Glass Pluck', pm=0.25, ratio2=5, decay=1.2, cutoff=9000, env_=0.0, extra=lambda p: p.op(1, unison=2, detune=5, spread=0.9))
pluck('Gated Pluck', pm=0.45, decay=1.5, hold=0.5, cutoff=4000, extra=lambda p: p.lfo(1, 'square', div='1/16').mod('lfo1', 'op1Level', -0.5))
pluck('Echo Pluck', pm=0.45, decay=0.3, cutoff=4500, extra=lambda p: p.delay(div='1/8T', feedback=0.6, pingpong=True, tone=0.5, mix=0.4))
pluck('Harp Pluck', pm=0.3, ratio2=2, decay=1.8, cutoff=6000, env_=0.2)
pluck('Kalimba Pluck', pm=0.25, ratio2=2, decay=0.9, ratio3=9, pm3=0.1, cutoff=8000, env_=0.0)

# ------------------------------------------------------- synth keys / organs --
p = P(EKEYS, 'FM E-Piano Deluxe')
p.op(1, ratio=1, level=1, vel=0.55, amp=adsr(0.002, 3.5, 0.0, 0.3, t=-0.6)).op(2, ratio=14, level=0.4, vel=0.95, amp=perc(0.002, 0.35)).pm(2, 1, 0.32)
p.op(3, ratio=1, level=0.8, vel=0.5, amp=adsr(0.002, 3.0, 0.0, 0.3, t=-0.6)).op(4, ratio=1, level=0.65, vel=0.85, amp=perc(0.002, 1.6)).pm(4, 3, 0.48)
p.op(5, ratio=1, fine=5, level=0.5, vel=0.5, amp=adsr(0.002, 2.5, 0.0, 0.3)).op(6, ratio=2, level=0.4, vel=0.9, amp=perc(0.002, 1.0)).pm(6, 5, 0.3)
p.carriers(1, 3, 5, level=0.6).lfo(1, 'sine', rate=4.8).mod('lfo1', 'op1Pan', 0.5).mod('lfo1', 'op3Pan', -0.5).chorus(rate=0.4, depth=0.25, mix=0.3).reverb(size=0.55, decay=0.45, mix=0.18)

def organ(name, drawbars, perc_=0.0, drive=0.0, leslie=0.0, cat=EKEYS):
    p = P(cat, name)
    for k, (r, l) in enumerate(drawbars, start=1):
        p.op(k, ratio=r, level=l, vel=0.15, amp=adsr(0.005, 0.05, 1, 0.05))
    p.carriers(*range(1, len(drawbars) + 1), level=0.5)
    if perc_: p.op(7, ratio=3, level=perc_, amp=perc(0.001, 0.3)).out(7, dry=0.5)
    if leslie: p.lfo(1, 'sine', rate=leslie).mod('lfo1', 'op1Pan', 0.5).mod('lfo1', 'op2Pan', -0.5).mod('lfo1', 'op1Fine', 0.03)
    if drive: p.dist('soft', drive=drive, tone=0.7, mix=0.6)
    p.reverb(size=0.5, decay=0.4, mix=0.15)
    return p
organ('Dirty Organ', [(1, 0.9), (2, 0.7), (3, 0.5), (4, 0.4), (0.5, 0.5)], perc_=0.3, drive=0.45, leslie=6.0)
organ('Reggae Organ', [(1, 0.8), (2, 0.6), (0.5, 0.4)], perc_=0.0, leslie=5.0).op(1, amp=adsr(0.005, 0.05, 1, 0.03)).comp(thresh=-12, ratio=4, attack=3)
organ('House Organ', [(1, 0.9), (2, 0.8), (3, 0.6), (4, 0.5), (0.5, 0.6)], perc_=0.4, drive=0.2, leslie=0.0).chorus(rate=0.8, depth=0.3, mix=0.3)
organ('Soft Jazz Organ', [(1, 0.8), (2, 0.4), (0.5, 0.6), (3, 0.2)], leslie=0.7)

p = P(EKEYS, 'Synth Clav')
p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.001, 1.2, 0.0, 0.08, t=-0.6)).op(2, ratio=1, level=0.85, vel=0.9, amp=perc(0.001, 0.3)).pm(2, 1, 0.55).fb(2, 0.3)
p.carriers(1, to='F1').flt(1, 'LP', cutoff=1500, reso=0.5, env=0.5, vel=0.3, cut=perc(0.001, 0.2)).phaser(rate=0.4, depth=0.6, stages=1, feedback=0.3, mix=0.35).comp(thresh=-16, ratio=4, attack=3)

p = P(EKEYS, 'Bell Keys')
p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.002, 2.5, 0.1, 0.6, t=-0.6)).op(2, ratio=3.5, level=0.5, vel=0.9, amp=perc(0.002, 1.2)).pm(2, 1, 0.35)
p.op(3, ratio=1, fine=5, level=0.6, amp=adsr(0.002, 2.0, 0.1, 0.6, t=-0.6)).op(4, ratio=7, level=0.3, amp=perc(0.002, 0.4)).pm(4, 3, 0.2).carriers(1, 3, level=0.8)
p.chorus(rate=0.3, depth=0.25, mix=0.3).reverb(size=0.7, decay=0.6, mix=0.3)

p = P(EKEYS, 'Glass Keys')
p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.005, 1.8, 0.2, 0.5, t=-0.6)).op(2, ratio=4, level=0.45, vel=0.9, amp=perc(0.005, 0.8)).pm(2, 1, 0.28)
p.op(3, ratio=2, level=0.5, vel=0.6, amp=adsr(0.005, 1.5, 0.2, 0.5)).carriers(1, 3, level=0.8).delay(div='1/8D', feedback=0.3, pingpong=True, tone=0.7, mix=0.2).reverb(size=0.65, decay=0.55, mix=0.25)

p = P(EKEYS, 'Lo-fi Keys')
p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.003, 2.0, 0.1, 0.3, t=-0.6)).op(2, ratio=1, level=0.6, vel=0.8, amp=perc(0.003, 1.0)).pm(2, 1, 0.4)
p.carriers(1, to='F1').flt(1, 'LP', cutoff=2200, key=0.3).lfo(1, 'sine', rate=0.7).mod('lfo1', 'op1Fine', 0.06).dist('crush', drive=0.25, tone=0.55, mix=0.5).chorus(rate=0.2, depth=0.3, mix=0.3).reverb(size=0.5, decay=0.5, mix=0.2)

p = P(EKEYS, 'Dream Keys')
p.op(1, ratio=1, level=1, unison=2, detune=6, spread=0.8, vel=0.5, amp=adsr(0.01, 2.5, 0.3, 1.0, t=-0.6)).op(2, ratio=2, level=0.5, vel=0.8, amp=perc(0.01, 1.5)).pm(2, 1, 0.3)
p.op(3, ratio=1, level=0.6, vel=0.4, amp=adsr(0.3, 1.0, 0.6, 1.2)).carriers(1, 3, level=0.8).delay(div='1/4D', feedback=0.4, pingpong=True, tone=0.6, mix=0.25).reverb(size=0.9, decay=0.8, mix=0.4)

p = P(EKEYS, '80s FM Keys')
p.op(1, ratio=1, level=1, vel=0.5, amp=adsr(0.002, 1.5, 0.3, 0.3, t=-0.6)).op(2, ratio=3, level=0.6, vel=0.9, amp=perc(0.002, 0.6)).pm(2, 1, 0.4)
p.op(3, ratio=1, fine=-6, level=0.7, amp=adsr(0.002, 1.5, 0.3, 0.3, t=-0.6)).op(4, ratio=5, level=0.3, amp=perc(0.002, 0.3)).pm(4, 3, 0.25).carriers(1, 3, level=0.8)
p.chorus(rate=0.9, depth=0.4, mix=0.4).reverb(size=0.6, decay=0.5, mix=0.22)

# ---------------------------------------------------------- chords / stabs ----
def stab(name, pm=0.5, fb=0.25, fifth=0.0, octave=0.0, unison=3, detune=12, decay=0.4, hold=0.0, cutoff=3500, drive=0.0, extra=None):
    p = P(STAB, name)
    a = adsr(0.004, decay, hold, 0.2, t=-0.5)
    p.op(1, ratio=1, level=1, unison=unison, detune=detune, spread=0.8, vel=0.4, amp=a)
    p.op(2, ratio=1, level=0.85, vel=0.6, amp=a).pm(2, 1, pm).fb(2, fb)
    if fifth: p.op(3, ratio=1.5, level=fifth, unison=2, detune=8, spread=0.8, amp=a).pm(2, 3, pm * 0.6).out(3, f1=0.8)
    if octave: p.op(4, ratio=2, level=octave, amp=a).pm(2, 4, pm * 0.5).out(4, f1=0.7)
    p.carriers(1, to='F1').flt(1, 'LP', cutoff=cutoff, key=0.3, vel=0.3, env=0.3, cut=perc(0.002, decay))
    if drive: p.dist('soft', drive=drive, mix=0.5)
    p.delay(div='1/8D', feedback=0.3, pingpong=True, tone=0.5, mix=0.2).reverb(size=0.6, decay=0.5, mix=0.2).comp(thresh=-14, ratio=3, attack=5)
    if extra: extra(p)
    return p
stab('House Stab', fifth=0.8, octave=0.5)
stab('Rave Stab', fifth=0.9, octave=0.6, pm=0.55, fb=0.35, unison=5, detune=18, cutoff=5000, drive=0.3)
stab('Power Chord', fifth=1.0, octave=0.7, pm=0.5, decay=1.0, hold=0.6, cutoff=3000, drive=0.4)
stab('Piano Stab', pm=0.42, unison=1, decay=0.8, cutoff=6000, extra=lambda p: p.op(3, ratio=7, level=0.3, amp=perc(0.001, 0.08)).pm(3, 1, 0.2))
stab('Organ Stab', pm=0.0, fifth=0.6, octave=0.8, unison=1, decay=0.2, hold=1.0, cutoff=8000, extra=lambda p: p.op(2, level=0.0))
stab('Brass Stab', pm=0.5, fb=0.2, fifth=0.5, decay=0.5, hold=0.3, cutoff=3000, extra=lambda p: p.op(2, mod=swell(0.08, 0.3, 0.6)))
stab('Detuned Stab', fifth=0.7, unison=6, detune=24, pm=0.45, cutoff=4000)
stab('Dub Chord', fifth=0.7, octave=0.3, pm=0.35, decay=0.3, cutoff=1800, extra=lambda p: p.delay(div='1/4D', feedback=0.6, pingpong=True, tone=0.3, mix=0.45))
stab('Garage Chord', fifth=0.6, octave=0.5, pm=0.45, decay=0.25, cutoff=4000, extra=lambda p: p.flt(1, reso=0.4))
stab('Dubstep Chord Stab', fifth=0.9, octave=0.5, pm=0.5, fb=0.35, unison=4, detune=16, decay=0.6, hold=0.5, cutoff=1200, drive=0.4,
     extra=lambda p: p.lfo(1, 'sine', div='1/8').mod('lfo1', 'flt1Cutoff', 0.35))

# --------------------------------------------------------- drums / percussion -
def drum(name, extra):
    p = P(DRUM, name)
    p.poly(8).p['bendRange'] = 0
    extra(p)
    return p
drum('Kick 808', lambda p: p.op(1, ratio=1, level=1, amp=perc(0.001, 0.9, t=-0.5), pitch=pitch_drop(0.9, 0.05), pitchamt=36, keytrack=0.0, fixed=True, hz=50).carriers(1)
     .dist('soft', drive=0.3, tone=0.4, mix=0.5).eq(low=2, lowf=60, lowcut=25).comp(thresh=-10, ratio=4, attack=5))
drum('Kick Punch', lambda p: p.op(1, ratio=1, level=1, amp=perc(0.001, 0.35), pitch=pitch_drop(1.0, 0.03), pitchamt=48, fixed=True, hz=55).op(2, wave='noise', level=0.3, amp=perc(0.001, 0.012)).carriers(1, 2)
     .dist('hard', drive=0.35, tone=0.5, mix=0.5).eq(low=3, lowf=70, lowcut=30, mid=2, midf=3000).comp(thresh=-10, ratio=6, attack=3))
drum('Kick Dubstep', lambda p: p.op(1, ratio=1, level=1, amp=perc(0.001, 0.55), pitch=pitch_drop(0.95, 0.04), pitchamt=40, fixed=True, hz=48).op(2, ratio=1, level=0.6, amp=perc(0.001, 0.02)).pm(2, 1, 0.4).carriers(1)
     .dist('soft', drive=0.45, tone=0.5, mix=0.6).eq(low=3, lowf=55, lowcut=28).comp(thresh=-10, ratio=6, attack=3, limit=True))
drum('Snare FM', lambda p: p.op(1, ratio=1, level=1, amp=perc(0.001, 0.2), pitch=pitch_drop(0.8, 0.03), pitchamt=24, fixed=True, hz=185).op(2, ratio=1, level=0.7, amp=perc(0.001, 0.08)).pm(2, 1, 0.5)
     .op(3, wave='noise', level=0.7, amp=perc(0.001, 0.22)).carriers(1).out(3, f1=1).flt(1, 'HP', cutoff=1200, reso=0.2)
     .dist('soft', drive=0.3, mix=0.4).eq(mid=3, midf=200, q=1.5, high=2, highf=6000).comp(thresh=-12, ratio=4, attack=2).reverb(size=0.3, decay=0.25, mix=0.1))
drum('Snare Noise', lambda p: p.op(1, wave='noise', level=1, amp=perc(0.001, 0.25)).op(2, ratio=1, level=0.6, amp=perc(0.001, 0.1), fixed=True, hz=200, pitch=pitch_drop(0.7, 0.02), pitchamt=24)
     .carriers(2).out(1, f1=1).flt(1, 'BP', cutoff=2500, reso=0.3).eq(high=3, highf=8000).comp(thresh=-12, ratio=4, attack=2))
drum('Clap', lambda p: p.op(1, wave='noise', level=1, amp=env([[0, 1], [0.012, 0.3, -0.5], [0.014, 1], [0.026, 0.3, -0.5], [0.028, 1], [0.04, 0.25, -0.5], [0.042, 0.9], [0.35, 0, -0.6]], sustain=-1))
     .op(2, wave='noise', level=1, amp=env([[0, 1], [0.012, 0.3, -0.5], [0.014, 1], [0.026, 0.3, -0.5], [0.028, 1], [0.04, 0.25, -0.5], [0.042, 0.9], [0.35, 0, -0.6]], sustain=-1))
     .carriers(1, 2, to='F1').out(1, dry=0.4).flt(1, 'BP', cutoff=1500, reso=0.35, slope=12).dist('soft', drive=0.3, mix=0.5).reverb(size=0.4, decay=0.35, mix=0.2).eq(high=2, highf=5000).comp(thresh=-12, ratio=4, attack=1))
drum('Hi-Hat Closed', lambda p: p.op(1, wave='noise', level=1, amp=perc(0.001, 0.05)).op(2, ratio=1, level=0.8, fixed=True, hz=6300, amp=perc(0.001, 0.04)).op(3, ratio=1, level=0.8, fixed=True, hz=9100, amp=perc(0.001, 0.04)).rm(2, 3, 0.8)
     .op(4, wave='noise', level=1, amp=perc(0.001, 0.05)).carriers(1, 3, 4, to='F1').out(1, dry=0.5).flt(1, 'HP', cutoff=6000, reso=0.2).eq(high=3, highf=10000).comp(thresh=-14, ratio=4, attack=1))
drum('Hi-Hat Open', lambda p: p.op(1, wave='noise', level=1, amp=perc(0.001, 0.45, t=-0.4)).op(2, ratio=1, level=0.5, fixed=True, hz=6300, amp=perc(0.001, 0.4)).op(3, ratio=1, level=0.5, fixed=True, hz=9100, amp=perc(0.001, 0.4)).rm(2, 3, 0.8)
     .carriers(1, 3, to='F1').flt(1, 'HP', cutoff=5500, reso=0.2).eq(high=2, highf=10000).comp(thresh=-14, ratio=4, attack=1))
drum('Tom', lambda p: p.op(1, ratio=1, level=1, amp=perc(0.001, 0.5), pitch=pitch_drop(0.8, 0.08), pitchamt=12).op(2, ratio=1, level=0.5, amp=perc(0.001, 0.15)).pm(2, 1, 0.35).op(3, wave='noise', level=0.15, amp=perc(0.001, 0.03))
     .carriers(1, 3).eq(low=2, lowf=120).comp(thresh=-12, ratio=4, attack=3).reverb(size=0.4, decay=0.3, mix=0.12))
drum('Rimshot', lambda p: p.op(1, ratio=1, level=1, fixed=True, hz=450, amp=perc(0.001, 0.06)).op(2, ratio=1, level=0.8, fixed=True, hz=1700, amp=perc(0.001, 0.03)).pm(2, 1, 0.6).op(3, wave='noise', level=0.6, amp=perc(0.001, 0.015))
     .op(4, ratio=1, level=1, fixed=True, hz=900, amp=perc(0.001, 0.05)).carriers(1, 3, 4).dist('soft', drive=0.3, mix=0.5).eq(mid=4, midf=2000, q=1.5).comp(thresh=-12, ratio=4, attack=1))
drum('Cowbell 808', lambda p: p.op(1, partials=[1, 0, 0.3], level=0.8, fixed=True, hz=540, amp=perc(0.001, 0.3)).op(2, partials=[1, 0, 0.3], level=0.8, fixed=True, hz=800, amp=perc(0.001, 0.3))
     .carriers(1, 2, to='F1').flt(1, 'BP', cutoff=1800, reso=0.3, slope=12).comp(thresh=-12, ratio=4, attack=1))
drum('Cymbal Crash', lambda p: p.op(1, wave='noise', level=1, amp=perc(0.001, 1.8, t=-0.3)).op(2, ratio=1, level=0.6, fixed=True, hz=5300, amp=perc(0.001, 1.5)).op(3, ratio=1, level=0.6, fixed=True, hz=7900, amp=perc(0.001, 1.5)).rm(2, 3, 0.8).pm(3, 2, 0.4)
     .carriers(1, 2, to='F1').flt(1, 'HP', cutoff=3500, reso=0.2).reverb(size=0.5, decay=0.5, mix=0.2).comp(thresh=-14, ratio=4, attack=1))
drum('Perc Blip', lambda p: p.op(1, ratio=1, level=1, amp=perc(0.001, 0.12)).op(2, ratio=5, level=0.6, amp=perc(0.001, 0.04)).pm(2, 1, 0.4).carriers(1).delay(div='1/16', feedback=0.4, pingpong=True, tone=0.6, mix=0.25).comp(thresh=-12, ratio=4, attack=1))
drum('Zap', lambda p: p.op(1, ratio=1, level=1, amp=perc(0.001, 0.25), pitch=pitch_drop(1.0, 0.18, t=-0.8), pitchamt=48).op(2, ratio=2, level=0.8, amp=perc(0.001, 0.2)).pm(2, 1, 0.5).fb(2, 0.3)
     .carriers(1).dist('soft', drive=0.3, mix=0.5).comp(thresh=-12, ratio=4, attack=1))

# ------------------------------------------------------------- fx / risers ---
def fx(name, extra):
    p = P(FXC, name)
    extra(p)
    return p
fx('Riser 2 Bars', lambda p: p.mono().op(1, ratio=1, level=1, unison=4, detune=20, spread=0.9, amp=adsr(0.2, 0.1, 1, 0.3, sync=True), pitch=env([[0, 0.25], [8, 1, 0.2], [9, 1]], sustain=2, sync=True), pitchamt=24)
   .op(2, ratio=1, level=0.8, amp=adsr(0.2, 0.1, 1, 0.3, sync=True), pitch=env([[0, 0.25], [8, 1, 0.2], [9, 1]], sustain=2, sync=True), pitchamt=24).pm(2, 1, 0.45).fb(2, 0.3)
   .op(3, wave='noise', level=0.4, amp=adsr(0.5, 0.1, 1, 0.3, sync=True)).carriers(1, 3, to='F1').flt(1, 'LP', cutoff=300, reso=0.4, slope=24, env=0.8, cut=env([[0, 0], [8, 1, 0.2], [9, 1]], sustain=2, sync=True))
   .lfo(1, 'sine', div='1/16').mod('lfo1', 'op1Level', -0.2).reverb(size=0.8, decay=0.7, mix=0.3).comp(thresh=-12, ratio=4, attack=10))
fx('Riser 4 Bars', lambda p: p.mono().op(1, ratio=1, level=1, unison=4, detune=20, spread=0.9, amp=adsr(0.5, 0.1, 1, 0.3, sync=True), pitch=env([[0, 0.3], [16, 1, 0.3], [17, 1]], sustain=2, sync=True), pitchamt=24)
   .op(2, ratio=1, level=0.8, amp=adsr(0.5, 0.1, 1, 0.3, sync=True)).pm(2, 1, 0.45).fb(2, 0.3).op(3, wave='noise', level=0.5, amp=adsr(1, 0.1, 1, 0.3, sync=True))
   .carriers(1, 3, to='F1').flt(1, 'LP', cutoff=250, reso=0.4, slope=24, env=0.85, cut=env([[0, 0], [16, 1, 0.3], [17, 1]], sustain=2, sync=True)).reverb(size=0.85, decay=0.75, mix=0.35).comp(thresh=-12, ratio=4, attack=10))
fx('Riser Noise', lambda p: p.mono().op(1, wave='noise', level=1, amp=adsr(0.3, 0.1, 1, 0.3, sync=True)).carriers(1, to='F1')
   .flt(1, 'BP', cutoff=200, reso=0.5, slope=12, env=1.0, cut=env([[0, 0], [8, 1, 0.3], [9, 1]], sustain=2, sync=True)).reverb(size=0.8, decay=0.7, mix=0.3).comp(thresh=-12, ratio=4, attack=10))
fx('Downlifter', lambda p: p.mono().op(1, ratio=1, level=1, unison=3, detune=15, spread=0.9, amp=adsr(0.01, 0.1, 1, 0.5, sync=True), pitch=env([[0, 0.9], [4, 0.2, -0.3], [5, 0.2]], sustain=2, sync=True), pitchamt=24)
   .op(2, ratio=1, level=0.8, amp=adsr(0.01, 0.1, 1, 0.5, sync=True)).pm(2, 1, 0.45).op(3, wave='noise', level=0.4, amp=adsr(0.01, 0.1, 1, 0.5, sync=True))
   .carriers(1, 3, to='F1').flt(1, 'LP', cutoff=8000, reso=0.4, slope=24, env=-0.8, cut=env([[0, 0], [4, 1, -0.3], [5, 1]], sustain=2, sync=True)).reverb(size=0.8, decay=0.7, mix=0.3).comp(thresh=-12, ratio=4, attack=10))
fx('Impact Boom', lambda p: p.op(1, ratio=1, level=1, fixed=True, hz=45, amp=perc(0.002, 2.5, t=-0.4), pitch=pitch_drop(0.9, 0.08), pitchamt=36).op(2, wave='noise', level=0.6, amp=perc(0.001, 0.6, t=-0.6))
   .carriers(1).out(2, f1=1).flt(1, 'LP', cutoff=800, reso=0.3, slope=24, env=0.5, cut=perc(0.001, 0.3)).dist('soft', drive=0.4, tone=0.4, mix=0.5).reverb(size=0.9, decay=0.8, mix=0.4).eq(low=3, lowf=50, lowcut=25).comp(thresh=-12, ratio=6, attack=3, limit=True))
fx('Sub Drop', lambda p: p.mono().op(1, ratio=1, level=1, amp=perc(0.005, 3.0, t=-0.3), pitch=env([[0, 1], [2.5, 0.0, -0.4], [3, 0]], sustain=-1), pitchamt=36, fixed=True, hz=60).carriers(1).eq(low=2, lowf=45, lowcut=22).comp(thresh=-10, ratio=4, attack=10))
fx('Laser Zap', lambda p: p.op(1, ratio=1, level=1, amp=perc(0.001, 0.3), pitch=pitch_drop(1.0, 0.25, t=-0.8), pitchamt=48).op(2, ratio=3, level=0.8, amp=perc(0.001, 0.25)).pm(2, 1, 0.5).fb(2, 0.4)
   .carriers(1).delay(div='1/16', feedback=0.5, pingpong=True, tone=0.6, mix=0.3).comp(thresh=-12, ratio=4, attack=1))
fx('Siren', lambda p: p.mono().op(1, ratio=1, level=1, amp=adsr(0.05, 0.1, 1, 0.2)).op(2, ratio=2, level=0.6, amp=adsr(0.05, 0.1, 1, 0.2)).pm(2, 1, 0.3).carriers(1)
   .lfo(1, 'tri', rate=0.6).mod('lfo1', 'op1Fine', 1.0).mod('lfo1', 'op2Fine', 1.0).delay(div='1/4', feedback=0.4, pingpong=True, mix=0.25).reverb(size=0.7, decay=0.6, mix=0.25))
fx('Alarm', lambda p: p.mono().op(1, partials=[1, 0, 0.33, 0, 0.2], level=1, amp=adsr(0.005, 0.1, 1, 0.05)).op(2, ratio=1.5, level=0.7, amp=adsr(0.005, 0.1, 1, 0.05)).carriers(1, 2)
   .lfo(1, 'square', div='1/8').mod('lfo1', 'op1Fine', 0.5).mod('lfo1', 'op2Fine', 0.5).dist('hard', drive=0.3, mix=0.5).delay(div='1/8', feedback=0.3, mix=0.2))
fx('Glitch S&H', lambda p: p.op(1, ratio=1, level=1, amp=adsr(0.005, 0.1, 1, 0.1)).op(2, ratio=2, level=0.8, amp=adsr(0.005, 0.1, 1, 0.1)).pm(2, 1, 0.45).carriers(1, to='F1').flt(1, 'LP', cutoff=1500, reso=0.5)
   .lfo(1, 'sh', div='1/16').mod('lfo1', 'op1Fine', 1.0).mod('lfo1', 'op2Fine', 1.0).mod('lfo1', 'flt1Cutoff', 0.4).lfo(2, 'square', div='1/16').mod('lfo2', 'op1Level', -0.4).dist('crush', drive=0.4, mix=0.6).delay(div='1/16', feedback=0.5, pingpong=True, mix=0.3))
fx('Dial-up', lambda p: p.op(1, ratio=1, level=1, amp=adsr(0.005, 0.1, 1, 0.05)).op(2, ratio=3, level=0.7, amp=adsr(0.005, 0.1, 1, 0.05)).pm(2, 1, 0.4).carriers(1)
   .lfo(1, 'sh', rate=14).mod('lfo1', 'op1Fine', 1.0).mod('lfo1', 'pm21', 0.3).lfo(2, 'sh', rate=23).mod('lfo2', 'op2Fine', 1.0).dist('crush', drive=0.3, mix=0.5))
fx('Thunder', lambda p: p.op(1, wave='noise', level=1, amp=env([[0, 0], [0.2, 1, 0.3], [1.5, 0.5, -0.3], [4, 0, -0.5]], sustain=-1)).op(2, ratio=1, level=0.8, fixed=True, hz=40, amp=perc(0.1, 3.0, t=-0.3))
   .carriers(2).out(1, f1=1).flt(1, 'LP', cutoff=400, reso=0.3, slope=24).lfo(1, 'sh', rate=9).mod('lfo1', 'flt1Cutoff', 0.3).reverb(size=0.95, decay=0.85, mix=0.4).eq(low=3, lowf=50).comp(thresh=-12, ratio=4, attack=10))
fx('Air Sweep', lambda p: p.mono().op(1, wave='noise', level=1, amp=adsr(0.3, 0.2, 0.9, 1.0)).carriers(1, to='F1').flt(1, 'BP', cutoff=800, reso=0.6, slope=12)
   .lfo(1, 'tri', div='1/1').mod('lfo1', 'flt1Cutoff', 0.6).reverb(size=0.8, decay=0.7, mix=0.35).comp(thresh=-12, ratio=4, attack=10))
fx('Wobble Riser', lambda p: p.mono().op(1, ratio=1, level=1, unison=3, detune=14, spread=0.9, amp=adsr(0.1, 0.1, 1, 0.3, sync=True), pitch=env([[0, 0.4], [8, 0.9, 0.2], [9, 0.9]], sustain=2, sync=True), pitchamt=24)
   .op(2, ratio=1, level=0.8, amp=adsr(0.1, 0.1, 1, 0.3, sync=True)).pm(2, 1, 0.45).fb(2, 0.3).carriers(1, to='F1').flt(1, 'LP', cutoff=400, reso=0.5, slope=24, env=0.6, cut=env([[0, 0], [8, 1, 0.2], [9, 1]], sustain=2, sync=True))
   .lfo(1, 'sine', div='1/16').mod('lfo1', 'flt1Cutoff', 0.35).dist('soft', drive=0.35, mix=0.6).reverb(size=0.8, decay=0.7, mix=0.3).comp(thresh=-12, ratio=4, attack=8))

# ================================================================== output ====
def main():
    names = [p.name for p in PRESETS]
    dup = {n for n in names if names.count(n) > 1}
    assert not dup, 'duplicate preset names: %s' % dup
    assert len(PRESETS) >= 200, 'expected at least 200 presets, have %d' % len(PRESETS)

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

    cats = []
    for p in PRESETS:
        if p.name in trims: p.p['presetGain'] = trims[p.name]
        if p.cat not in cats: cats.append(p.cat)
    doc = {
        'format': 'Eight Ball Factory Presets',
        'version': 1,
        'note': 'GENERATED by presets/make_presets.py: edit the recipes there, not this file. Values = parameter defaults <- '
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
