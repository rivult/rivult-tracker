/** Danger zone: irreversible cloud-account deletion.
 *
 * Deliberately three steps (reveal -> type DELETE -> password) because the
 * action cannot be undone. The server re-checks the password too — this isn't
 * the security boundary, it's the "did you mean to" boundary.
 *
 * Local games are NOT touched: they live in this PC's database, and losing
 * your history because you closed a cloud account would be a nasty surprise.
 */
import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { api } from "../api/client";
import { Card, CardLabel } from "../components/shared";

const CONFIRM_WORD = "DELETE";

export function DeleteAccountCard({ email, onDeleted }: { email: string; onDeleted: () => void }) {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = confirm.trim().toUpperCase() === CONFIRM_WORD && password.length > 0;

  const reset = () => {
    setOpen(false);
    setConfirm("");
    setPassword("");
    setError(null);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.cloudDeleteAccount(password);
      if (r.deleted) {
        reset();
        onDeleted();
      } else {
        setError(
          r.code === "NETWORK"
            ? "Can't reach Rivult — check your connection and try again."
            : (r.error ?? "Couldn't delete the account."),
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="space-y-3 border-danger/40 p-6">
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-danger" />
        <CardLabel>Danger zone</CardLabel>
      </div>

      {!open ? (
        <>
          <p className="text-sm text-muted-foreground">
            Permanently delete <span className="text-foreground">{email}</span> and everything
            synced to it — games, tags and devices. This cannot be undone. Any active subscription
            is cancelled first. Your games stay on this PC.
          </p>
          <button
            onClick={() => setOpen(true)}
            className="rounded-md border border-danger/50 px-3 py-1.5 text-sm text-danger transition-colors hover:bg-danger/10"
          >
            Delete account
          </button>
        </>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-danger">
            This permanently erases your cloud account and everything synced to it. It cannot be
            undone.
          </p>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="del-confirm">
              Type {CONFIRM_WORD} to confirm
            </label>
            <input
              id="del-confirm"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder={CONFIRM_WORD}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-danger/60"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor="del-password">
              Your password
            </label>
            <input
              id="del-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-danger/60"
            />
          </div>
          {error && <div className="text-sm text-danger">{error}</div>}
          <div className="flex items-center gap-2">
            <button
              onClick={() => void submit()}
              disabled={!ready || busy}
              className="rounded-md bg-danger px-3 py-1.5 text-sm font-medium text-white transition-opacity hover:bg-danger/90 disabled:opacity-50"
            >
              {busy ? "Deleting…" : "Delete permanently"}
            </button>
            <button
              onClick={reset}
              disabled={busy}
              className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
