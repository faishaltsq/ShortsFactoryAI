# Planner produksi, scheduler, dan job lease

Status awal selalu **disabled**. Modul ini tidak menjalankan daemon, mendaftarkan startup/task OS, menghubungkan akun, atau mengunggah video. Membuat rencana tidak memberi izin eksekusi. API dan observer Hermes tetap read-only.

## CLI operator

Jalankan dari root repository. `--db` dan `--artifacts` adalah opsi global, sebelum subcommand. Tanpa override, database berada di `data/jobs/factory.db`; artifact root adalah direktori database.

```bash
uv run python scripts/schedule.py --help
uv run python scripts/schedule.py status

# Hanya menyimpan rencana; tidak memanggil provider.
uv run python scripts/schedule.py plan \
  --start '2026-10-22T10:00:00+07:00' \
  --videos-per-day 2 --genres science,history,fiction --mode mock

uv run python scripts/schedule.py pause
```

`status` membuka database read-only; bila database belum ada, ia melaporkan `enabled: false` tanpa membuat file/direktori. `--help`, `status`, `plan`, dan `pause` tidak memuat runner/provider.

Operator baru dapat mengizinkan dispatch dengan perintah eksplisit berikut; `enable` sendiri tidak memulai proses:

```bash
uv run python scripts/schedule.py enable --confirm-unattended
uv run python scripts/schedule.py tick --limit 1
uv run python scripts/schedule.py pause
```

`tick` ditolak ketika belum di-enable. Satu panggilan memproses maksimal `--limit` slot (default 1; rentang 1–1000). CLI menjalankan pipeline hanya sampai `READY_FOR_APPROVAL`, bukan approval operator maupun upload. Mode berasal dari slot/job yang tersimpan, bukan override saat tick. `--mode live` pada rencana tidak menjalankan provider saat perencanaan, tetapi tick yang diizinkan akan memakai provider live. Tidak ada enable produksi atau tick provider live yang dijalankan sebagai bagian implementasi/verifikasi modul ini.

Exit code: `0` berhasil/tidak ada dispatch, `1` terdapat slot gagal pada tick, `2` input, izin, atau database bermasalah. RETRY dilaporkan melalui JSON dan tidak tidur di dalam tick.

## Kontrak perencanaan

```python
from datetime import datetime
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.planner import ProductionPlanner

planner = ProductionPlanner(store)
plan = planner.plan_seven_days(
    start=datetime.fromisoformat("2026-10-22T10:00:00+07:00"),
    videos_per_day=2,
    genres=["science", "history", "fiction"],
    provider_mode="mock",
    max_attempts=3,
    retry_base_s=60,
)
restored = planner.get(plan.id)
```

- `start` wajib timezone-aware. Offset tersimpan; untuk kalender dengan DST, gunakan `ZoneInfo` di Python atau CLI `--timezone Europe/London` bila data IANA tersedia di mesin.
- Tepat tujuh window kalender dimulai dari jam lokal `start`. Setiap window dibagi merata menurut panjang aktual window dalam UTC. Dengan dua video/hari, di zona UTC+07 tetap, start 10:00 menghasilkan 10:00 dan 22:00 lokal.
- Genre divalidasi terhadap enum domain dan dirotasi kontinu antar-slot/hari. Nilai yang dipersist: `genre`, `provider_mode`, `plan_id`, `plan_slot_id`, dan `due_at` di payload job.
- `videos_per_day`: integer 1–1000. `max_attempts`: integer 1–10, **termasuk upaya awal dan dispatch yang terinterupsi**. `retry_base_s`: finite, lebih dari 0, maksimal 86400.
- Identitas plan deterministik dari seluruh spesifikasi. Pengulangan spesifikasi sama, termasuk setelah reopen/reboot, mengembalikan slot dan job yang sama. Nilai retry `60` dan `60.0` identik.
- `(plan_id, day_index, slot_index)`, `job_id`, dan due time UTC memiliki unique constraint. Plan berbeda yang memakai due time sama ditolak sebagai overlap, bukan menggandakan produksi atau mengganti mode diam-diam.
- Plan, seluruh slot, job, dan event pembuatan job masuk dalam **satu transaksi SQLite**. Kegagalan di tengah perencanaan me-rollback seluruh transaksi. Snapshot `job.json` ditulis setelah commit; panggilan plan ulang memperbaiki snapshot yang belum sempat ditulis tanpa membuat job baru.
- Penulisan artifact menggunakan temporary filename unik dan atomic replace; konflik berbagi-file Windows memiliki empat upaya terbatas.

## Kontrak scheduler dan recovery

```python
from packages.core.orchestration.scheduler import DispatchResult, Scheduler

# Callback wajib memakai lease job di runner dan memvalidasi hasil/artifact.
def run_job(job_id: str, *, provider_mode: str) -> DispatchResult:
    report = configured_runner(provider_mode).run(job_id, stop_at=production_boundary)
    return DispatchResult(success=report.ok, retryable=True)

scheduler = Scheduler(store, runner=run_job)
scheduler.status()
scheduler.enable(operator_confirmed=True)  # hanya atas tindakan operator
report = scheduler.tick(limit=1)
scheduler.pause()
scheduler.events()
```

State slot: `PENDING → DISPATCHED → COMPLETE | RETRY | FAILED`. State ini terpisah dari `JobState`; `COMPLETE` berarti batas produksi callback sudah selesai, **bukan** video dipublikasikan. Adapter CLI membatasi keberhasilan ke `READY_FOR_APPROVAL`. Callback aplikasi lain bertanggung jawab pada validasi artifact dan batas akhirnya.

Claim slot, penghitung attempt, token dispatch acak, serta event dispatch disimpan atomik dengan `BEGIN IMMEDIATE`. Callback harus mengembalikan `DispatchResult`; kontrak yang salah menjadi kegagalan terminal. Exception biasa menjadi retryable; `KeyboardInterrupt`/`SystemExit` dibiarkan menginterupsi sehingga dispatch persisten dapat dipulihkan. DB hanya menyimpan kode error generik, bukan pesan exception/provider yang mungkin memuat rahasia.

Backoff adalah `min(86400, retry_base_s * 2**(attempts - 1))`. Batas upaya dan waktu retry dipersist per-slot, tidak reset ketika aplikasi direstart. Tiap tick memulihkan maksimal 1000 dispatch kedaluwarsa:

1. Dispatch TTL adalah 120 detik. Recovery menunggu TTL habis **dan** lease pipeline job tidak lagi aktif.
2. Lease pipeline yang masih hidup tidak dicuri atau dilepas, meskipun TTL dispatch sudah lewat.
3. Upaya yang terinterupsi dihitung. Recovery menjadi RETRY dengan backoff atau FAILED jika cap tercapai.
4. Bila job sudah `READY_FOR_APPROVAL`/`APPROVED`/tahap publikasi setelah crash sebelum acknowledgment, slot menjadi COMPLETE tanpa mengulang runner.
5. `CANCELLED`, `REJECTED`, dan `BLOCKED` tidak dikirim kembali ke runner. Perubahan operator juga diperiksa ketika hasil callback dicatat.
6. Hasil dispatch lama tidak dapat menimpa dispatch pengganti: settlement mengecek token dispatch.

Enable/pause tersimpan di `scheduler_control`; perubahan dicatat di `scheduler_events`. Pause menghentikan claim baru, tidak mematikan pekerjaan yang sudah berjalan. Status `next_due_at` adalah due time rencana paling awal yang belum selesai; backoff aktual tersimpan terpisah sebagai `next_attempt_at`.

## Owned renewable leases: integrasi runner

```python
from packages.core.orchestration.leases import LeaseKeeper, LeaseLostError
from packages.core.orchestration.jobstore import ConcurrentTransition

# Semua waktu expiry memakai clock UTC milik store, dapat diinjeksi saat tes.
token = store.acquire_lease(job_id, ttl_s=1800)  # str token | None
if token is not None:
    with LeaseKeeper(store, job_id, token, ttl_s=1800, interval_s=None) as keeper:
        keeper.check()           # renew + validasi ownership; raise LeaseLostError
        run_bounded_stage()
        keeper.check()           # periksa lagi sebelum transisi/menulis hasil

# Alternatif tanpa keeper, misalnya operasi approve/reject yang singkat:
token = store.acquire_lease(job_id, ttl_s=60)
if token is not None:
    try:
        store.transition(job_id, target_state, expected_state=previous_state)
    finally:
        store.release_lease(job_id, token)
```

API tepat:

- `JobStore(db_path, artifacts_root, *, clock=None)`; `clock()` wajib mengembalikan datetime aware. `utc_now()` mengonversinya ke UTC.
- `acquire_lease(job_id, ttl_s=1800, owner=None) -> str | None`; default token acak baru. Bila memakai `owner`, berikan token unik baru untuk setiap akuisisi, jangan label worker yang dipakai ulang.
- `renew_lease(job_id, token, ttl_s=1800) -> bool`; hanya pemilik lease **yang belum expired** dapat renew. Lease lama tidak dapat dihidupkan kembali.
- `release_lease(job_id, token) -> bool`; token lama/salah tidak bisa melepas lease pengganti.
- `LeaseKeeper(store, job_id, token, *, ttl_s=1800, interval_s=None)`; interval default TTL/3, wajib positif dan lebih pendek dari TTL. Context ini single-use. Thread heartbeat berjalan hanya selama context aktif, bergabung saat keluar, dan melepas token miliknya saja. `heartbeat() -> bool`; `check() -> None` melempar `LeaseLostError`. Exit normal juga mengecek kepemilikan; exception awal tidak ditimpa oleh deteksi lease hilang.
- `transition(..., expected_state=JobState.X)` melakukan compare-and-set dalam transaksi. Ketidakcocokan memunculkan `ConcurrentTransition(ValueError)` dan tidak menulis state/event baru.
- `try_lock(job_id)`/`unlock(job_id)` tetap tersedia. Token disimpan per-instance JobStore; `unlock` oleh instance lain atau owner lama adalah no-op, tidak pernah clear lease orang lain. Untuk tahap panjang, gunakan keeper, bukan wrapper lama tanpa heartbeat.

Migrasi jobstore hanya menambah kolom lease. Lock lama `locked_at` dipertahankan sebagai lease selama sisa TTL 30 menit, tanpa menghapus job/event. Waktu acquire/renew dibaca **setelah** memperoleh write transaction agar antrean database tidak menghasilkan lease yang sudah kedaluwarsa.

Lease mencegah overlap pada runner yang bekerja sama; heartbeat tidak membatalkan subprocess yang sudah berjalan. `PipelineRunner` memakai `LeaseKeeper` sepanjang eksekusi, memeriksa kepemilikan sebelum/sesudah tahap dan sebelum transisi, lalu berhenti tanpa menandai job `FAILED` jika lease hilang. Tahap panjang tetap perlu batas waktu proses dan artifact resume yang idempotent. Integrasi runner/approval berada di luar file scheduler; gunakan payload genre rencana ketika memilih genre produksi.

## Verifikasi offline

```bash
uv run pytest tests/test_scheduler.py tests/test_leases.py
uv run ruff check packages/core/orchestration/jobstore.py \
  packages/core/orchestration/leases.py packages/core/orchestration/planner.py \
  packages/core/orchestration/scheduler.py scripts/schedule.py \
  tests/test_scheduler.py tests/test_leases.py
```

Tes memakai SQLite dan artifact root sementara, clock terinjeksi, serta callback/provider boundary offline. Cakupan termasuk tujuh hari/rotasi/dedupe, dua planner/store berlomba, migrasi lock lama, stale owner/dispatch, heartbeat saat tahap terblokir, reboot di tengah dispatch, crash setelah pipeline selesai, cap/backoff, operator pause/enable, dan CLI offline. Pengujian adapter CLI tidak menjalankan TTS/render/provider live atau upload.
