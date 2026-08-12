#!/bin/bash
set -e
cd /app/media

# Generate WAV sources using sox (G.711 A-law, 8 kHz mono)
# Silence: 10 seconds of silence
sox -n -r 8000 -c 1 -e a-law silence.wav trim 0 10

# Tone: 10 seconds of 440Hz sine wave
sox -n -r 8000 -c 1 -e a-law tone.wav synth 10 sine 440

# Voice: spoken-like pattern (alternating tones)
sox -n -r 8000 -c 1 -e a-law voice.wav synth 10 sine 300:600 gain -10

# Convert WAVs to real RTP pcaps — SIPp's play_pcap_audio requires libpcap
# files with RTP packets, not renamed WAVs.
for f in silence tone voice; do
    python3 /app/media/wav_to_pcap.py ${f}.wav ${f}.pcap
done

echo "Media files ready."
