# Publishing YouTube: operator-only, private-first

Tidak ada koneksi akun, upload, atau automation yang dijalankan saat implementasi/test.
Import modul, `--help`, dan `--status JOB_ID` tidak membuat request Google. Tidak ada integrasi publish otomatis ke runner, scheduler, dashboard, API, atau Hermes.

## Integrasi kontrak (untuk pemilik core)

- Daftarkan `publishing.json` → `packages.core.publishing.contracts.PublishingArtifact` dalam `ARTIFACT_MODELS`, lalu ekspor schema `config/schemas/publishing.json` dari `model_json_schema(by_alias=True)`.
- Publisher memakai `approval.require_eligible(store, job_id)`, `approval.approval_fingerprint(store, job_id)`, dan payload **`approved_inputs_sha256`**, `approved_by`, `approved_at`, `provider_mode='live'`. Mock selalu ditolak walaupun lolos gate lokal.
- Publisher memakai owner-token `acquire_lease(job_id, ttl_s=600)`, `renew_lease(job_id, token, ttl_s=600)`, `release_lease(job_id, token)` dan `transition(..., expected_state=...)`.
- Private tanpa jadwal tetap **PRIVATE_UPLOAD**, bukan SCHEDULED. Allow-list sudah memuat **PRIVATE_UPLOAD → PUBLISHED** untuk `--publish-now`; publisher memeriksanya sebelum perubahan remote. Jalur terjadwal memakai PRIVATE_UPLOAD → SCHEDULED → PUBLISHED. Pembacaan ulang remote menolak disclosure kids/synthetic yang bertentangan dengan pilihan operator. Jangan menambahkan auto-public ke runner.
- Service domain (`service.py`) terpisah dari adapter HTTP (`youtube.py`, `oauth.py`, `transport.py`), tidak mengubah FastAPI.

## Persiapan operator

Di Google Cloud project milik operator, aktifkan YouTube Data API dan buat OAuth client bertipe **Desktop app**. Tempatkan JSON client resmi sebagai `client.json` di direktori konfigurasi terlindungi di luar repo:

- Windows: `%LOCALAPPDATA%/ShortsFactoryAI/youtube/`
- POSIX: `$XDG_CONFIG_HOME/ShortsFactoryAI/youtube/`, atau `~/.config/ShortsFactoryAI/youtube/`

Tidak ada parameter client secret, access token, refresh token, atau signed upload URI di CLI. Jangan menempatkannya di `.env`, DB, artifact job, atau git. Aplikasi mengunci DACL Windows ke current user + SYSTEM, atau mode POSIX 0700/0600; kegagalan proteksi menghentikan operasi. Penulisan token/session bersifat atomic, token refresh memakai OS-held file lock. Root konfigurasi di dalam repo atau melalui symlink/junction ditolak.

Scope yang diminta adalah `https://www.googleapis.com/auth/youtube.force-ssl`: scope ini didokumentasikan untuk insert dan status update. `youtube.upload` saja tidak cukup untuk `videos.update`.

## Perintah eksplisit

Contoh berikut adalah dokumentasi, **bukan perintah yang sudah dijalankan**:

```bash
# Satu-satunya perintah yang membuka browser dan memulai OAuth.
uv run python scripts/publish.py --connect

# Lokal saja; tidak me-refresh token atau menghubungi Google.
uv run python scripts/publish.py --status JOB_ID

# Hanya job live APPROVED dengan approval yang masih sesuai media/artifact.
# Category/kids/synthetic disclosure wajib dipilih operator.
uv run python scripts/publish.py --upload JOB_ID --category-id 22 --not-made-for-kids --synthetic-media

# Terpisah dari approval/upload; waktu ber-offset timezone, minimum 2 menit ke depan.
uv run python scripts/publish.py --schedule JOB_ID --publish-at '2027-01-01T18:00:00+07:00' --confirm --by operator

# Public hanya dengan izin eksplisit ini dan read-back status public.
uv run python scripts/publish.py --publish-now JOB_ID --confirm --by operator

# Membaca ulang remote; tidak mengirim upload/status update.
uv run python scripts/publish.py --reconcile JOB_ID --confirm --by operator

# Hanya bila operator sudah mencocokkan video di YouTube Studio secara manual.
uv run python scripts/publish.py --reconcile JOB_ID --video-id VIDEO_ID --confirm --by operator
```

`--data-root PATH` memilih runtime lokal lain (default `data/`). `--config-dir PATH` memilih direktori rahasia di luar repo. Tidak ada unattended/recurring switch.

## OAuth dan transport

Installed-app OAuth memakai random ephemeral `127.0.0.1` loopback port, browser sistem, state acak one-use, PKCE S256, callback path tetap, deadline 120 detik, dan token endpoint HTTPS resmi. Callback state/PKCE/host/duplicate/error/expiry yang salah tidak menukar code. Authorization-code exchange tidak diulang otomatis setelah response hilang; operator harus menjalankan `--connect` lagi.

HTTP client bisa diinjeksi (`httpx.Client(transport=httpx.MockTransport(...))`). Timeout per request default 20 detik, maksimal 30; retry operasi aman default 3, maksimum 5, exponential backoff dibatasi. GET/probe dan refresh dibatasi; insert, chunk, serta status update tidak diulang buta. HTTP transport logging dibisukan karena log URL standar httpx dapat mengekspos signed resumable URI. Error keluar berupa kode tetap tanpa body, credential, atau URI.

## Resume, idempotensi, dan hasil ambigu

`publishing.json` menyimpan checksum media yang disetujui, ukuran/offset, fase in-flight, opsi disclosure, remote video ID, hasil read-back, jadwal, dan identitas approval publikasi. Token dan signed URI hanya berada di protected store.

Sebelum insert, fase `initiating` ditulis. Setelah session URI diterima, URI disimpan terlindungi sebelum mengirim media. Restart mem-probe URI untuk offset authoritative dengan `Content-Range: bytes */TOTAL`; chunk berikutnya dibaca ulang dari file asli. Checksum/approval dan owner lease diperiksa sebelum side effect dan sebelum klaim sukses.

Setelah final PUT, remote ID ditulis sebelum `videos.list(part=status,id=EXACT_ID)`. PRIVATE_UPLOAD baru dinyatakan setelah ID, privacy private tanpa publishAt, upload status, dan media/approval cocok. Perintah upload ulang dengan remote ID hanya membaca ulang video, tidak membuat insert baru.

Response insert hilang, URI hilang/expired, offset invalid/no-progress berulang, atau hasil remote yang tak dapat dipastikan akan berhenti untuk rekonsiliasi manual, bukan membuat video baru. Marker `scheduling`/`publishing` yang tersisa juga tidak mengulang update otomatis: gunakan `--reconcile`. Jika video ID belum diketahui, operator harus menemukan dan mencocokkan video manual terlebih dahulu; API tidak menyediakan checksum media upload yang dapat membuktikan kecocokan otomatis. Tidak ada reset otomatis maupun fallback blind reinsert.

Scheduling mengirim `privacyStatus='private'` dan `publishAt` UTC secara eksplisit; read-back harus sama. Publish-now mengirim `privacyStatus='public'` setelah konfirmasi terpisah; read-back harus public sebelum state PUBLISHED. Nilai status writable lain dipertahankan dari read-back sebelum update.

## Verifikasi offline

```bash
.venv/Scripts/python.exe -m pytest tests/test_publishing.py -q
.venv/Scripts/python.exe -m ruff check packages/core/publishing scripts/publish.py tests/test_publishing.py
```

Fixture memakai transport HTTP in-memory dan direktori runtime/secret sementara. Synthetic test bytes hanya untuk pengujian boundary publisher; test service secara eksplisit menginjeksi gate QC/fingerprint. Produksi tetap memakai gate media fisik asli tanpa opt-out CLI.

## Referensi resmi

- [Google installed-app OAuth, loopback, PKCE, refresh](https://developers.google.com/identity/protocols/oauth2/native-app)
- [YouTube resumable protocol, session URI, probe dan offsets](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol)
- [videos.insert: scope dan private explicit](https://developers.google.com/youtube/v3/docs/videos/insert)
- [videos.update: scope, status/publishAt dan replacement semantics](https://developers.google.com/youtube/v3/docs/videos/update)
- [videos.list: exact ID read-back](https://developers.google.com/youtube/v3/docs/videos/list)
