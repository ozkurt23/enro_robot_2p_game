#!/usr/bin/env bash
# Optional CPU-only local speech recognition; no system packages are changed.
set -Eeuo pipefail
ENRO_SPEECH_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENRO_SPEECH_SOURCE="$ENRO_SPEECH_ROOT/.deps/whisper.cpp"
ENRO_SPEECH_MODEL="$ENRO_SPEECH_ROOT/.models/ggml-base.bin"
ENRO_SPEECH_COMMIT=a8d002cfd879315632a579e73f0148d06959de36
ENRO_SPEECH_HASH=60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe
for enro_tool in git cmake c++ curl sha256sum arecord; do
    command -v "$enro_tool" >/dev/null || { echo "Eksik araç: $enro_tool" >&2; exit 1; }
done
mkdir -p "$ENRO_SPEECH_ROOT/.deps" "$ENRO_SPEECH_ROOT/.models"
if [[ ! -d "$ENRO_SPEECH_SOURCE" ]]; then
    git clone --depth 1 --branch v1.7.6 https://github.com/ggml-org/whisper.cpp.git "$ENRO_SPEECH_SOURCE"
fi
[[ "$(git -C "$ENRO_SPEECH_SOURCE" rev-parse HEAD)" == "$ENRO_SPEECH_COMMIT" ]] || {
    echo "whisper.cpp pin uyuşmuyor; mevcut kaynak korunuyor." >&2; exit 1;
}
[[ -z "$(git -C "$ENRO_SPEECH_SOURCE" status --porcelain --untracked-files=no)" ]] || {
    echo "whisper.cpp kaynağı değiştirilmiş; mevcut değişiklikler korunuyor." >&2; exit 1;
}
cmake -S "$ENRO_SPEECH_SOURCE" -B "$ENRO_SPEECH_SOURCE/build" \
    -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DWHISPER_BUILD_TESTS=OFF
cmake --build "$ENRO_SPEECH_SOURCE/build" --target whisper-cli --parallel 4
if [[ ! -f "$ENRO_SPEECH_MODEL" ]]; then
    ENRO_SPEECH_DOWNLOAD="$(mktemp "$ENRO_SPEECH_ROOT/.models/whisper-download.XXXXXX")"
    trap 'rm -f -- "$ENRO_SPEECH_DOWNLOAD"' EXIT
    curl --fail --location --retry 3 \
        https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base.bin \
        --output "$ENRO_SPEECH_DOWNLOAD"
    [[ "$(sha256sum "$ENRO_SPEECH_DOWNLOAD" | cut -d ' ' -f1)" == "$ENRO_SPEECH_HASH" ]]
    mv -- "$ENRO_SPEECH_DOWNLOAD" "$ENRO_SPEECH_MODEL"
    trap - EXIT
fi
[[ "$(sha256sum "$ENRO_SPEECH_MODEL" | cut -d ' ' -f1)" == "$ENRO_SPEECH_HASH" ]]
echo "Yerel Türkçe ses paketi hazır. Bas-konuş dökümü gönderilmeden önce panelde gösterilir."
