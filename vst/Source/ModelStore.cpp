#include "ModelStore.h"

namespace eightball
{
namespace
{
juce::Array<juce::var> floatsToArray (const float* v, int n, int digits)
{
    juce::Array<juce::var> a;
    for (int i = 0; i < n; ++i) a.add (juce::String (v[i], digits).getDoubleValue());
    return a;
}
int arrayToFloats (const juce::var& v, float* out, int n, float lo, float hi)
{
    const auto* a = v.getArray();
    if (a == nullptr) return 0;
    const int count = juce::jmin (n, a->size());
    for (int i = 0; i < count; ++i) out[i] = juce::jlimit (lo, hi, (float) (double) (*a)[i]);
    return count;
}
} // namespace

juce::var waveToJson (const WaveSpec& w)
{
    auto* o = new juce::DynamicObject();
    if (w.drawn)
    {
        o->setProperty ("mode", "drawn");
        o->setProperty ("shape", floatsToArray (w.shape.data(), kDrawPoints, 4));
    }
    else
    {
        o->setProperty ("mode", "harmonic");
        int n = 0;
        for (int i = 0; i < kMaxPartials; ++i) if (w.level[(size_t) i] != 0.0f || w.phase[(size_t) i] != 0.0f) n = i + 1;
        o->setProperty ("levels", floatsToArray (w.level.data(), n, 4));
        o->setProperty ("phases", floatsToArray (w.phase.data(), n, 4));
    }
    return juce::var (o);
}

bool waveFromJson (const juce::var& v, WaveSpec& w)
{
    if (! v.isObject()) return false;
    WaveSpec out;
    out.drawn = v["mode"].toString() == "drawn";
    if (out.drawn)
    {
        if (arrayToFloats (v["shape"], out.shape.data(), kDrawPoints, -1.0f, 1.0f) < 2) return false;
    }
    else
    {
        if (arrayToFloats (v["levels"], out.level.data(), kMaxPartials, 0.0f, 1.0f) < 1) return false;
        arrayToFloats (v["phases"], out.phase.data(), kMaxPartials, 0.0f, 1.0f);
    }
    w = out;
    return true;
}

juce::var envToJson (const EnvSpec& e)
{
    auto* o = new juce::DynamicObject();
    juce::Array<juce::var> pts;
    for (int i = 0; i < e.numPoints; ++i)
    {
        const auto& p = e.pts[(size_t) i];
        juce::Array<juce::var> pt { juce::String (p.time, 4).getDoubleValue(), juce::String (p.level, 4).getDoubleValue(),
                                    juce::String (p.tension, 3).getDoubleValue() };
        pts.add (juce::var (pt));
    }
    o->setProperty ("points", pts);
    o->setProperty ("sustain", e.sustain);
    o->setProperty ("loopStart", e.loopStart);
    o->setProperty ("loopEnd", e.loopEnd);
    o->setProperty ("sync", e.sync);
    return juce::var (o);
}

bool envFromJson (const juce::var& v, EnvSpec& e)
{
    if (! v.isObject()) return false;
    const auto* pts = v["points"].getArray();
    if (pts == nullptr || pts->isEmpty()) return false;
    EnvSpec out;
    double lastT = -1;
    for (const auto& p : *pts)
    {
        const auto* a = p.getArray();
        if (a == nullptr || a->size() < 2) return false;
        double t = juce::jmax (0.0, (double) (*a)[0]);
        if (t < lastT) t = lastT;   // keep points sorted
        lastT = t;
        out.add ((float) t, juce::jlimit (0.0f, 1.0f, (float) (double) (*a)[1]),
                 a->size() > 2 ? juce::jlimit (-1.0f, 1.0f, (float) (double) (*a)[2]) : 0.0f);
    }
    const int n = out.numPoints;
    out.sustain = juce::jlimit (-1, n - 1, (int) v.getProperty ("sustain", -1));
    out.loopStart = juce::jlimit (-1, n - 1, (int) v.getProperty ("loopStart", -1));
    out.loopEnd = juce::jlimit (-1, n - 1, (int) v.getProperty ("loopEnd", -1));
    if (out.loopEnd <= out.loopStart) out.loopStart = out.loopEnd = -1;
    out.sync = (bool) v.getProperty ("sync", false);
    e = out;
    return true;
}

juce::var lfoShapeToJson (const LfoShape& s) { return floatsToArray (s.pts.data(), kLfoShapePoints, 4); }
bool lfoShapeFromJson (const juce::var& v, LfoShape& s)
{
    LfoShape out;
    if (arrayToFloats (v, out.pts.data(), kLfoShapePoints, -1.0f, 1.0f) < 2) return false;
    s = out;
    return true;
}

juce::String envKey (int index)
{
    if (index < kNumOpEnvs)
    {
        const char* kinds[] { "Amp", "Pitch", "Mod" };
        return "op" + juce::String (index / kOpEnvKinds + 1) + kinds[index % kOpEnvKinds];
    }
    const int f = index - kNumOpEnvs;
    const char* kinds[] { "Cutoff", "Level" };
    return "flt" + juce::String (f / kFltEnvKinds + 1) + kinds[f % kFltEnvKinds];
}

int envIndexForKey (const juce::String& key)
{
    for (int i = 0; i < kNumEnvs; ++i) if (envKey (i) == key) return i;
    return -1;
}

void modelDataToJson (const ModelData& d, juce::DynamicObject& into)
{
    auto* waves = new juce::DynamicObject();
    for (int k = 0; k < kNumOps; ++k) waves->setProperty (juce::String (k + 1), waveToJson (d.waves[(size_t) k]));
    into.setProperty ("waves", juce::var (waves));
    auto* envs = new juce::DynamicObject();
    for (int i = 0; i < kNumEnvs; ++i) envs->setProperty (envKey (i), envToJson (d.envs[(size_t) i]));
    into.setProperty ("envs", juce::var (envs));
    auto* shapes = new juce::DynamicObject();
    for (int l = 0; l < kNumLfos; ++l) shapes->setProperty (juce::String (l + 1), lfoShapeToJson (d.lfoShapes[(size_t) l]));
    into.setProperty ("lfoShapes", juce::var (shapes));
}

void modelDataFromJson (const juce::var& obj, ModelData& out)
{
    if (! obj.isObject()) return;
    if (const auto* w = obj["waves"].getDynamicObject())
        for (const auto& prop : w->getProperties())
        {
            const int k = prop.name.toString().getIntValue() - 1;
            if (k >= 0 && k < kNumOps) waveFromJson (prop.value, out.waves[(size_t) k]);
        }
    if (const auto* e = obj["envs"].getDynamicObject())
        for (const auto& prop : e->getProperties())
        {
            const int i = envIndexForKey (prop.name.toString());
            if (i >= 0) envFromJson (prop.value, out.envs[(size_t) i]);
        }
    if (const auto* s = obj["lfoShapes"].getDynamicObject())
        for (const auto& prop : s->getProperties())
        {
            const int l = prop.name.toString().getIntValue() - 1;
            if (l >= 0 && l < kNumLfos) lfoShapeFromJson (prop.value, out.lfoShapes[(size_t) l]);
        }
}

//==============================================================================
ModelStore::ModelStore()
{
    for (int k = 0; k < kNumOps; ++k)
    {
        auto t = std::make_shared<Wavetable>();
        buildWavetable (current.waves[(size_t) k], *t);
        tables[(size_t) k] = t;
    }
    publish();
}

ModelStore::~ModelStore()
{
    delete incoming.exchange (nullptr);
    delete retired.exchange (nullptr);
    delete active;
}

void ModelStore::publish()
{
    auto* p = new Published();
    for (int k = 0; k < kNumOps; ++k)
    {
        p->tables[(size_t) k] = tables[(size_t) k];
        p->model.tables[(size_t) k] = tables[(size_t) k].get();
    }
    p->model.envs = current.envs;
    p->model.lfoShapes = current.lfoShapes;
    collectRetired();
    delete incoming.exchange (p);   // an older, never-used post is safe to drop
    ++version;
}

void ModelStore::setWave (int op, const WaveSpec& w)
{
    if (op < 0 || op >= kNumOps) return;
    current.waves[(size_t) op] = w;
    auto t = std::make_shared<Wavetable>();
    buildWavetable (w, *t);
    tables[(size_t) op] = t;
    publish();
}

void ModelStore::setEnv (int index, const EnvSpec& e)
{
    if (index < 0 || index >= kNumEnvs) return;
    current.envs[(size_t) index] = e;
    publish();
}

void ModelStore::setLfoShape (int lfo, const LfoShape& s)
{
    if (lfo < 0 || lfo >= kNumLfos) return;
    current.lfoShapes[(size_t) lfo] = s;
    publish();
}

void ModelStore::setAll (const ModelData& d)
{
    for (int k = 0; k < kNumOps; ++k)
    {
        // rebuild only the tables whose spec changed
        const auto& a = current.waves[(size_t) k];
        const auto& b = d.waves[(size_t) k];
        const bool same = a.drawn == b.drawn && (a.drawn ? a.shape == b.shape : (a.level == b.level && a.phase == b.phase));
        if (! same)
        {
            auto t = std::make_shared<Wavetable>();
            buildWavetable (b, *t);
            tables[(size_t) k] = t;
        }
    }
    current = d;
    publish();
}

const Model* ModelStore::takeIncoming()
{
    if (retired.load() != nullptr) return nullptr;   // wait until the message thread freed the last one
    if (auto* p = incoming.exchange (nullptr))
    {
        retired.store (active);
        active = p;
        return &p->model;
    }
    return nullptr;
}

void ModelStore::collectRetired()
{
    delete retired.exchange (nullptr);
}
} // namespace eightball
