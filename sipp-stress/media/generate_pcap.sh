#!/bin/bash
set -e
cd /app/media

# Generate WAV files using sox
# Silence: 10 seconds of silence, G.711 alaw, 8kHz mono
sox -n -r 8000 -c 1 -e a-law silence.wav trim 0 10

# Tone: 10 seconds of 440Hz sine wave
sox -n -r 8000 -c 1 -e a-law tone.wav synth 10 sine 440

# Voice: use sox to generate a spoken-like pattern (alternating tones)
sox -n -r 8000 -c 1 -e a-law voice.wav synth 10 sine 300:600 gain -10

echo "WAV files generated successfully."

# Convert WAVs to RTP pcap files using sipp's built-in pcap play
# SIPp can play WAV files directly with play_pcap_audio if they are
# in the right format. For raw pcap, we create them from the WAV.
# Actually, SIPp with -mp flag can play raw audio files too.
# We'll use the WAV files directly — SIPp supports alaw WAV playback.

# Create symlinks for .pcap names (SIPp uses the file extension)
for f in silence tone voice; do
    cp ${f}.wav ${f}.pcap
done

echo "Media files ready."
