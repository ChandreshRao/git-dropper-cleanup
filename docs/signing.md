# Commit signing (optional)

**Signed commits are not required** to remove the dropper. Configure signing only when you want **Verified** on GitHub.

Neither **git-dropper-cleanup** nor **sign-history** runs `git config`. Set signing on the machine that performs rewrites, and keep that key off any host that may still be compromised.

## Setup (SSH, recommended)

1. Create a key if you do not already have one:

   ```bash
   ssh-keygen -t ed25519 -C "git-signing" -f ~/.ssh/id_ed25519_sign
   ```

   Use a key **without a passphrase** for non-interactive rewrites (`sign-history --fix` or automated `--rewrite`).

2. Add the **public** key on GitHub: **Settings → SSH and GPG keys → New SSH key → Key type: Signing key**. Paste `~/.ssh/id_ed25519_sign.pub`.

3. Point git at the public key and enable signing:

   ```bash
   git config --global gpg.format ssh
   git config --global user.signingkey ~/.ssh/id_ed25519_sign.pub
   git config --global commit.gpgsign true
   ```

   On Windows, prefer a full path such as `C:/Users/you/.ssh/id_ed25519_sign.pub` if `~` does not expand.

4. Set **`user.email`** to the **noreply address GitHub shows for your account** (Settings → Emails). A valid signature with a different committer email often stays **Unverified**.

5. Confirm:

   ```bash
   git commit --allow-empty -m "signing test"
   git log -1 --show-signature
   ```

**GPG** also works if `user.signingkey` is set and `git commit -S` succeeds. Both tools use that key when signing.

## After unsigned dropper cleanup

If you rewrote without a signing key, commits are unsigned. After setup above, either:

- Run **git-dropper-cleanup** `--rewrite` again to resign dropper-related commits, or
- Use **sign-history** when the only issue is wrong emails or missing signatures on otherwise clean content.

## sign-history

**sign-history** is separate from **git-dropper-cleanup** (git-dropper-cleanup never calls it). Use it after dropper cleanup when you want history to show **Verified**.

```bash
uv run sign-history /path/to/clone
uv run sign-history /path/to/clone --fix
uv run sign-history /path/to/clone --fix --push --push-main
```

Finish dropper removal first ([README](../README.md)). Do not run `npm` or `vite` until `--check` is clean.

### What GitHub checks

A commit is **Verified** when **both** are true:

- The signature matches a **Signing key** on the account.
- The **committer email** matches that account’s expected noreply address.

### Email and name (`--email` / `--name`)

Both flags are **optional**.

| Flag | When set | When omitted |
| --- | --- | --- |
| **`--email`** | That address is the verify target. | Clone’s **`user.email`**. |
| **`--name`** | Name written when emails are replaced. | Clone’s **`user.name`** (or a short form of the email). |

If **`--email`** is omitted and the clone has no **`user.email`**, the tool exits and asks you to pass **`--email`**.

**Check the printed `account email:` line** before **`--fix`**. A wrong target rewrites history to the wrong identity.

```bash
# Default: target = user.email in the clone
uv run sign-history /path/to/clone

# Explicit GitHub noreply (or other) address
uv run sign-history /path/to/clone \
  --email 12345678+you@users.noreply.github.com \
  --name "Your Name"
```

### Check / fix / push

A plain run is **read-only**. It lists mismatched emails and unsigned commits. Exit **`1`** if anything would show **Unverified**; exit **`0`** when everything matches and is signed.

Pass **`--fix`** only when printed addresses are not legitimate. The worktree must match **`HEAD`**:

```bash
git -C /path/to/clone restore .
uv run sign-history /path/to/clone --fix
```

**`--fix`** replaces author and committer on **all branches and tags**, and **signs every commit**. The private key must unlock **without a passphrase**.

Push with **`--force-with-lease`**. Default branches need **`--push-main`**:

```bash
uv run sign-history /path/to/clone --fix --push --push-main
```
