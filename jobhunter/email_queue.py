"""Fila persistente de Gmail SMTP processada pela automação no Actions."""
import json
import secrets
import time
from .job_identity import resolve


class EmailQueue:
    def __init__(self, store):
        self.store = store

    def enqueue(self, user_id, recipient, jobs):
        identifier = secrets.token_hex(16)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            selected = []
            for job in jobs:
                canonical = resolve(db, job['id'], user_id)
                pending = db.execute('SELECT 1 FROM email_pending WHERE user_id=? AND job_id=?', (user_id, canonical)).fetchone()
                delivered = db.execute('SELECT 1 FROM deliveries d LEFT JOIN job_aliases a ON a.user_id=d.user_id AND a.source_id=d.job_id '
                                       'WHERE d.user_id=? AND d.channel=? AND COALESCE(a.job_id,d.job_id)=?', (user_id, 'email', canonical)).fetchone()
                if not pending and not delivered:
                    db.execute('INSERT INTO email_pending VALUES(?,?,?)', (user_id, canonical, identifier))
                    selected.append(job)
            if selected:
                db.execute('INSERT INTO email_outbox(id,user_id,recipient,payload,status,available) VALUES(?,?,?,?,?,?)',
                           (identifier, user_id, recipient, json.dumps(selected), 'queued', time.time()))
        return len(selected)

    def process(self, sender, maximum=20):
        sent, failed = 0, 0
        for _ in range(maximum):
            now = time.time()
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                # Uma tentativa interrompida durante SMTP não é repetida automaticamente,
                # pois o provedor pode ter aceitado a mensagem antes da interrupção.
                db.execute("UPDATE email_outbox SET status='uncertain' WHERE status='sending' AND lease<?", (now,))
                row = db.execute("SELECT * FROM email_outbox WHERE status='queued' AND available<=? ORDER BY available LIMIT 1", (now,)).fetchone()
                if not row:
                    break
                row = dict(row)
                db.execute("UPDATE email_outbox SET status='sending',attempts=attempts+1,lease=? WHERE id=?", (now + 300, row['id']))
            jobs = json.loads(row['payload'])
            try:
                sender(row['recipient'], jobs)
            except Exception:
                # Sem expor destinatários ou credenciais nos logs do runner.
                with self.store.connection() as db:
                    db.execute("UPDATE email_outbox SET status='error',lease=0 WHERE id=?", (row['id'],))
                failed += 1
                continue
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                for job in jobs:
                    db.execute('INSERT INTO deliveries VALUES(?,?,?) ON CONFLICT(user_id,job_id,channel) DO NOTHING',
                               (row['user_id'], resolve(db, job['id'], row['user_id']), 'email'))
                db.execute("UPDATE email_outbox SET status='sent',lease=0 WHERE id=?", (row['id'],))
                db.execute('DELETE FROM email_pending WHERE outbox_id=?', (row['id'],))
            sent += len(jobs)
        return {'sent_jobs': sent, 'failed_batches': failed}

    def status(self, user_id):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute('SELECT id,status,attempts FROM email_outbox WHERE user_id=? ORDER BY available DESC LIMIT 20', (user_id,))]

    def retry(self, identifier, user_id):
        with self.store.connection() as db:
            cursor = db.execute("UPDATE email_outbox SET status='queued',available=?,lease=0 WHERE id=? AND user_id=? AND status IN ('error','uncertain') AND attempts<3", (time.time(), identifier, user_id))
            return bool(cursor.rowcount)
