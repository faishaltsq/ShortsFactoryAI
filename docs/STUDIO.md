# Studio — event bridge, worker, API/SSE, dashboard

Dokumen hasil dan batasan untuk konsol **Pixel Production Studio**. Angka di bawah berasal dari eksekusi nyata di mesin ini (Windows 11, Ryzen 5 7640HS, 15.2 GB RAM), bukan perkiraan.

## 1. Yang terpasang

| Lapisan | File | Fungsi |
| --- | --- | --- |
| Event bridge | `packages/core/observability/projection.py` (`StudioService`) | Membaca `studio_events` + `jobs` → snapshot tunggal untuk API |
| Event bridge | `packages/core/observability/store.py` (`StudioEventStore`) | Tulis + halamanan event dengan cursor (`page(after=...)`) |
| Lifecycle worker | `packages/core/observability/lifecycle.py` (`RunObserver`, `LifecycleWorker`) | Emit event dari worker pipeline; loop pengamat state job |
| API | `apps/api/main.py` (`create_app`) + `apps/api/server.py` | `/api/studio/snapshot`, `/api/studio/stream` (SSE), `/api/jobs/<id>/video` |
| API | `apps/api/streaming.py` | Generator SSE dengan `after=<cursor>` dan heartbeat |
| Dashboard | `apps/dashboard/src/app/page.tsx` | Reducer studio: snapshot, event, koneksi, mode, job terpilih |
| Dashboard | `apps/dashboard/src/lib/api.ts` | `fetchSnapshot` + `StudioStream` (backoff, `retry()` manual) |
| Dashboard | `apps/dashboard/src/components/{Office,Panels}.tsx` | Ruang kerja piksel, antrean, inspector, pipeline, preview |

`apps/api/server.py` dibuat terpisah supaya mengimpor `apps.api.main` tidak membuka database sebagai efek samping; pengujian membangun aplikasinya sendiri di atas store.

## 2. Cara menjalankan

```bash
uv run uvicorn apps.api.server:app --host 127.0.0.1 --port 8018
cd apps/dashboard && npm run build && npm run start   # 127.0.0.1:3018
```

Proxy Next memetakan `/api/*` ke `8018`, jadi dashboard membuka satu origin saja (CORS tidak terlibat).

## 3. Pengukuran render nyata + respons UI

Probe: `uv run python scripts/studio_probe.py --port 8018 --poll-ms 200` → `evidence/studio-probe.json`.

Job `89dc199b959242b3`, `provider_mode=mock` untuk tahap LLM, TTS Edge nyata, Remotion + FFmpeg nyata, `stop_at=TECHNICAL_QC`.

| Tahap | Waktu |
| --- | --- |
| IDEA_DISCOVERY | 39 ms |
| TOPIC_SELECTED | 48 ms |
| SCRIPT_GENERATED | 45 ms |
| CREATIVE_REVIEW | 68 ms |
| STORYBOARD_READY | 45 ms |
| ASSETS_READY | 44 ms |
| AUDIO_READY | 6.872 ms |
| RENDERING | 79.759 ms |
| TECHNICAL_QC | 1.577 ms |
| **Total run** | **88,6 detik** |

Selama render berjalan, probe mem-poll snapshot tiap 200 ms dan mengikuti stream SSE:

| Metrik | Nilai |
| --- | --- |
| Poll `/api/studio/snapshot` | 323 sampel, p50 **64,22 ms**, p95 **112,89 ms**, maks **206,7 ms**, 0 kegagalan |
| Lag tulis-SSE (SQLite → stream) | 177 sampel, p50 **213,2 ms**, p95 **467,37 ms**, maks **505,51 ms** |
| Event | **179 ditulis, 179 terkirim** (100%) |

Artefak diverifikasi dengan `ffprobe` dan `qc.json`:

- H.264 1080×1920 + AAC, durasi **36,608 detik**, ukuran **2.852.953 byte**.
- **16/16** pemeriksaan teknis `true` (resolusi, FPS, codec, frame count, durasi narasi, subtitle bounds, loudness, true peak, black gap, silence, frozen scene).
- Audio fisik: **-16,01 LUFS** integrated, **-5,1 dBTP**.
- `render_sha256`: `5f90bfae1d3bbf0360176bbfbb71ae9d0b3d59ac742da29ca8e6a40ac251afad`.
- State akhir job: `TECHNICAL_QC`. Editorial/factual QC masih `false` → `needs_review`, tidak dipublikasikan (aturan: unggahan privat dulu, publik hanya setelah approval).

Respons UI saat render berjalan (`evidence/studio-browser.json`, diambil ketika RENDERING aktif):

| Metrik | Saat render | Setelah render |
| --- | --- | --- |
| Halaman siap | 180 ms | 141 ms |
| Stream `connected` | 303 ms | 332 ms |
| Klik workstation → inspector (p50) | 57 ms | 52 ms |
| Klik workstation → inspector (maks) | 130 ms | 68 ms |
| `domContentLoaded` / `load` | 34 / 128 ms | 22 / 69 ms |

Screenshot: `evidence/studio-desktop.png`.

## 4. Quality gates

| Gate | Hasil |
| --- | --- |
| `uv run pytest` | `80 passed, 1 warning in 12.20s`, exit 0 |
| `uv run ruff check .` | `All checks passed!` |
| `uv run python scripts/export_schemas.py --check` | `12 artifact schemas verified` |
| `uv run python scripts/check_secrets.py` | `Secret scan: 0 findings across 117 text files` |
| `npx tsc --noEmit` (dashboard) | exit 0 |
| `npm test` (unit, vitest) | `pass 13`, `fail 0` |
| `npm run build` (Next 15) | sukses, static prerender |
| `npx playwright test` (e2e) | **5 passed (6,4s)** |
| `npm audit --omit=dev` | `found 0 vulnerabilities` |

e2e mencakup: snapshot live dari API, klik workstation → inspector, ganti mode demo/production, putus-pasang stream (reconnect) tanpa kehilangan bukti yang sudah diterima, dan reduced-motion (karakter diam, tidak berpura-pura bekerja).

Batas Hermes ditanam sebagai pengujian di `tests/test_studio_stream_live.py`: satu arah saja — API boleh membaca status Hermes, Hermes tidak pernah dipanggil oleh endpoint stream. Pipeline hidup (worker menulis event → SSE terkirim) juga diuji di sana.

## 5. Batasan yang diketahui

1. **Lag SSE dibatasi polling DB 0,5 detik.** `stream_events` membaca `studio_events` tiap ~0,5 detik, jadi p95 ~467 ms dan maks ~505 ms itu perilaku desain, bukan anomali. Menekan angka itu berarti memperkecil interval atau memakai notifikasi lain (mis. hook SQLite).
2. **`PipelineRunner.run` berhenti di `STORYBOARD_READY` secara default.** Tanpa `stop_at=JobState.TECHNICAL_QC`, tidak ada audio/render/QC. Probe sudah meneruskannya; pemanggil lain harus sadar default ini.
3. **Status peran berasal dari event terakhir yang tersimpan.** Ketika job aktif belum punya event untuk sebuah role, dashboard menampilkan event terakhir role itu lintas job (fallback `projectAgents`). Itu disengaja: menampilkan status terakhir yang diketahui, bukan mengarang status.
4. **Progres numerik tidak selalu ada.** Event `completed` sering tanpa `progress`. UI memetakannya menjadi 100% pada tahap selesai, dan inspector menuliskan `100% (selesai tanpa progres numerik)` supaya tidak terbaca sebagai pengukuran yang memang ada.
5. **Preview hanya menampilkan job dengan MP4 terverifikasi.** Job lain menampilkan `Belum ada MP4 terverifikasi`; tidak ada player yang menunjuk file yang belum lolos verifikasi.
6. **Batas approval tetap di sisi server.** Dashboard hanya menampilkan flag `approval_required`; keputusan tetap di operator, unggahan privat dulu.
7. **Tidak ada autentikasi.** Ini konsol localhost satu operator. Membuka port ke jaringan tanpa lapisan auth akan mengekspos seluruh log dan preview.
8. **Belum diverifikasi untuk kasus ini**: render simultan dua job di satu mesin (lock per job ada, beban CPU belum diuji), perilaku stream saat API restart di tengah render, dan retina/layar kecil (screenshot hanya 1440×900).
9. **`npm audit` hanya dependensi produksi**, dan scanner rahasia berbasis pola — keduanya bukan audit keamanan penuh.

## 6. Peta bukti

```
evidence/studio-probe.json    angka probe API/SSE/stage saat render nyata
evidence/studio-browser.json  metrik browser + path screenshot
evidence/studio-desktop.png   tangkapan layar konsol
tests/test_studio_stream_live.py   uji pipeline hidup + batas Hermes
apps/dashboard/tests/e2e/studio.spec.ts   5 skenario e2e
```
