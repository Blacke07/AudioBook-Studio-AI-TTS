// spk-batch.cpp: speaker embeddings for many WAV files with one model load.
//
// Loads the speaker encoder of a Base talker GGUF once, then reads one UTF-8
// WAV path per line on stdin and writes one line per file on stdout:
//   OK <dim> v0 v1 ... v(dim-1)     or     ERR <message>
// Used by the audiobook app to check that every generated passage keeps the
// identity of its fixed voice (cosine similarity of these x-vectors).

#include "audio-io.h"
#include "backend.h"
#include "gguf-weights.h"
#include "speaker-encoder-extract.h"
#include "speaker-encoder-weights.h"
#include "utf8.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

int main(int argc, char ** argv) {
    utf8_init(&argc, &argv);
    const char * talker_path = NULL;
    const char * device      = NULL;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--talker") == 0 && i + 1 < argc) {
            talker_path = argv[++i];
        } else if (strcmp(argv[i], "--device") == 0 && i + 1 < argc) {
            device = argv[++i];
        }
    }
    if (!talker_path) {
        fprintf(stderr, "Usage: %s --talker <base talker gguf> [--device CPU|CUDA0]  (WAV paths on stdin)\n", argv[0]);
        return 1;
    }
    if (device && !backend_check_device(device)) {
        return 1;
    }
    BackendPair bp = backend_init("Spk", device);
    if (!bp.backend) {
        fprintf(stderr, "[Spk] FATAL: backend init failed\n");
        return 1;
    }
    GGUFModel gf = {};
    if (!gf_load(&gf, talker_path)) {
        fprintf(stderr, "[Spk] FATAL: cannot open %s\n", talker_path);
        return 1;
    }
    SpeakerEncoderWeights sw = {};
    bool                  loaded = speaker_encoder_weights_load(&sw, gf, bp.backend);
    gf_close(&gf);
    if (!loaded || sw.weight_buf == NULL) {
        fprintf(stderr, "[Spk] FATAL: %s has no speaker encoder (Base only)\n", talker_path);
        return 1;
    }
    ggml_backend_sched_t sched = backend_sched_new(bp, 4096);
    fprintf(stdout, "READY %d\n", sw.enc_dim);
    fflush(stdout);

    char line[4096];
    while (fgets(line, sizeof(line), stdin)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r')) {
            line[--n] = 0;
        }
        if (!n) {
            continue;
        }
        int     T     = 0;
        float * audio = audio_read_mono(line, 24000, &T);
        if (!audio || T < 2400) {
            fprintf(stdout, "ERR cannot read or too short\n");
            fflush(stdout);
            free(audio);
            continue;
        }
        std::vector<float> emb;
        bool               ok = speaker_encoder_extract(&sw, sched, audio, T, emb);
        free(audio);
        if (!ok || (int) emb.size() != sw.enc_dim) {
            fprintf(stdout, "ERR extraction failed\n");
        } else {
            fprintf(stdout, "OK %d", sw.enc_dim);
            for (float v : emb) {
                fprintf(stdout, " %.6g", v);
            }
            fprintf(stdout, "\n");
        }
        fflush(stdout);
    }
    ggml_backend_sched_free(sched);
    speaker_encoder_weights_free(&sw);
    backend_release(bp.backend, bp.cpu_backend);
    return 0;
}
