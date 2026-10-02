---
sidebar_position: 4
title: File access (SFTP)
---

# File access (SFTP)

Most apps let you browse and download their stored files, such as an Immich photo library, with an SFTP client. Access is read-only: files cannot be uploaded, changed or deleted this way. The [product guides](/apps/products) say whether an app offers file access and which files it shows.

## 1. Create an SSH key

SFTP access uses an SSH key instead of a password. A key is a pair of files: a private key that stays on your computer, and a public key (ending in `.pub`) that you give to Freepod. If you already have one, skip to step 2.

On Windows 10 or later (PowerShell), macOS or Linux (Terminal), run:

```bash
ssh-keygen -t ed25519
```

Press Enter to accept the default location. Optionally, enter a passphrase to protect the key. This creates `id_ed25519` (private) and `id_ed25519.pub` (public) in the `.ssh` folder in your home folder.

## 2. Add the key to your account

1. In Freepod, go to **Settings → SSH keys** and select **Add key**.
2. Drop the `id_ed25519.pub` file on the dialog, or paste its contents.
3. Optionally, enter a label, and select **Add key**.

Never share the private key file, the one without `.pub`. A key works for all your apps.

## 3. Get the connection details

Select **Files** on the app's card. It shows:

| Field | Value |
| --- | --- |
| Host | `freepod.eu` |
| Port | `22` |
| Username | The app's identifier, unique per app |

## 4. Connect

Any SFTP client works. Use protocol **SFTP**, the host, port and username from step 3, and your private key file (`id_ed25519`) for authentication. No password is used.

| Client | Platform | Where to set the private key |
| --- | --- | --- |
| [Cyberduck](https://cyberduck.io) | macOS, Windows | **SSH Private Key** in the connection dialog |
| [FileZilla](https://filezilla-project.org) | macOS, Windows, Linux | **Edit → Settings → Connection → SFTP → Add key file** |
| [WinSCP](https://winscp.net) | Windows | **Advanced → SSH → Authentication → Private key file** |

FileZilla and WinSCP offer to convert the key to their own format; accept.

On the command line:

```bash
sftp -i ~/.ssh/id_ed25519 <username>@freepod.eu
```
