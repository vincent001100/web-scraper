"""Our own background music for Pet Shelf videos: a light plucked tune made from scratch with
numbers (no samples, no copied melody), so Solvix owns it fully. python3 pet_shelf_music.py out.wav seconds"""
import sys, wave
import numpy as np

SR = 44100
rng = np.random.default_rng(7)

def pluck(freq, dur, decay=0.996):
    """Karplus-Strong: a burst of noise in a short loop sounds like a plucked string."""
    n = int(SR * dur); period = int(SR / freq)
    buf = rng.uniform(-1, 1, period); out = np.empty(n)
    for i in range(n):
        out[i] = buf[i % period]
        buf[i % period] = decay * 0.5 * (buf[i % period] + buf[(i + 1) % period])
    return out * np.linspace(1, 0.6, n)

def note(name):
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    return 440 * 2 ** ((names[name[0]] + 12 * (int(name[1]) - 4)) / 12)

def song(seconds, bpm=104):
    beat = 60 / bpm; total = np.zeros(int(SR * (seconds + 2)))
    chords = [("C3", ["C4", "E4", "G4", "E4"]), ("A2", ["A3", "C4", "E4", "C4"]),
              ("F2", ["F3", "A3", "C4", "A3"]), ("G2", ["G3", "B3", "D4", "B3"])]
    melody = ["E5", "G5", "A5", "G5", "E5", "D5", "C5", "D5"]
    t, bar = 0.0, 0
    while t < seconds:
        root, arp = chords[bar % 4]
        def add(sig, at, gain):
            i = int(at * SR); seg = sig[: len(total) - i]; total[i:i + len(seg)] += gain * seg
        add(pluck(note(root), beat * 4, 0.998), t, 0.35)
        for k in range(8):
            add(pluck(note(arp[k % 4]), beat, 0.995), t + k * beat / 2, 0.22)
        if bar % 2 == 1:
            add(pluck(note(melody[(bar // 2) % 8]), beat * 2, 0.997), t + beat, 0.28)
            add(pluck(note(melody[(bar // 2 + 3) % 8]), beat * 2, 0.997), t + beat * 3, 0.24)
        for k in range(8):                       # soft shaker on the off-beats
            n = int(0.04 * SR); hiss = rng.normal(0, 1, n) * np.exp(-np.linspace(0, 8, n))
            add(hiss, t + k * beat / 2 + beat / 4, 0.03)
        t += beat * 4; bar += 1
    total = total[: int(SR * seconds)]
    fade = int(SR * 1.5); total[-fade:] *= np.linspace(1, 0, fade); total[: int(SR * 0.3)] *= np.linspace(0, 1, int(SR * 0.3))
    total = total / np.max(np.abs(total))
    total = np.tanh(2.2 * total) / np.tanh(2.2)          # gentle squeeze so it isn't too quiet on phones
    return total * 0.85

if __name__ == "__main__":
    out, seconds = sys.argv[1], float(sys.argv[2])
    data = (song(seconds) * 32767).astype(np.int16)
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(data.tobytes())
    print("wrote", out)
