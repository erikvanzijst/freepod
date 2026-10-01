import type { SvgIconComponent } from '@mui/icons-material'
import LayersRoundedIcon from '@mui/icons-material/LayersRounded'
import StorageRoundedIcon from '@mui/icons-material/StorageRounded'
import CloudQueueRoundedIcon from '@mui/icons-material/CloudQueueRounded'
import TuneRoundedIcon from '@mui/icons-material/TuneRounded'
import KeyRoundedIcon from '@mui/icons-material/KeyRounded'
import TerminalRoundedIcon from '@mui/icons-material/TerminalRounded'
import { accent } from '../landingTokens'
import type { Snippet } from './CodeBlock'

export interface Feature {
  id: string
  icon: SvgIconComponent
  color: string
  title: string
  blurb: string
  snippets: Snippet[]
}

export const features: Feature[] = [
  {
    id: 'stack',
    icon: LayersRoundedIcon,
    color: accent.blue,
    title: 'Any stack, or a Dockerfile',
    blurb:
      'Node, Python, Go, Ruby, Java, PHP, Rust and more are detected from your source and built without a Dockerfile. If you do have one, we\'ll use that instead.',
    snippets: [
      {
        label: 'Terminal',
        lang: 'shell',
        code: `# No Dockerfile? The stack is detected for you.
$ ls
package.json  index.js
$ freepod deploy

# Brought your own? It's used as-is.
$ ls
Dockerfile  go.mod  main.go
$ freepod deploy`,
      },
    ],
  },
  {
    id: 'postgres',
    icon: StorageRoundedIcon,
    color: accent.cyan,
    title: 'A Postgres database',
    blurb:
      'Every app gets its own PostgreSQL database. DATABASE_URL is already in the environment, so your ORM connects as-is. There is nothing to provision.',
    snippets: [
      {
        label: 'Python',
        lang: 'python',
        code: `import os, psycopg

with psycopg.connect(os.environ["DATABASE_URL"]) as db:
    db.execute("INSERT INTO links (slug, url) VALUES (%s, %s)", (slug, url))`,
      },
      {
        label: 'Node',
        lang: 'js',
        code: `import pg from 'pg'

const db = new pg.Pool({ connectionString: process.env.DATABASE_URL })
await db.query('INSERT INTO links (slug, url) VALUES ($1, $2)', [slug, url])`,
      },
      {
        label: 'Go',
        lang: 'go',
        code: `db, _ := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))

db.Exec(ctx, "INSERT INTO links (slug, url) VALUES ($1, $2)", slug, url)`,
      },
    ],
  },
  {
    id: 'storage',
    icon: CloudQueueRoundedIcon,
    color: accent.magenta,
    title: 'Object storage',
    blurb:
      'A private S3-compatible bucket per app, with credentials in the standard AWS_* variables. Any S3 SDK works, and presigned URLs go straight to the browser.',
    snippets: [
      {
        label: 'Python',
        lang: 'python',
        code: `import boto3, os

s3 = boto3.client("s3")  # credentials come from the environment
obj = {"Bucket": os.environ["S3_BUCKET"], "Key": "avatars/ada.png"}

s3.put_object(**obj, Body=photo)
url = s3.generate_presigned_url("get_object", Params=obj)  # public for 1h`,
      },
      {
        label: 'Node',
        lang: 'js',
        code: `import { S3Client, PutObjectCommand, GetObjectCommand } from '@aws-sdk/client-s3'
import { getSignedUrl } from '@aws-sdk/s3-request-presigner'

const s3 = new S3Client({ forcePathStyle: true })
const obj = { Bucket: process.env.S3_BUCKET, Key: 'avatars/ada.png' }

await s3.send(new PutObjectCommand({ ...obj, Body: photo }))
const url = await getSignedUrl(s3, new GetObjectCommand(obj), { expiresIn: 3600 })`,
      },
      {
        label: 'Go',
        lang: 'go',
        code: `cfg, _ := config.LoadDefaultConfig(ctx)
client := s3.NewFromConfig(cfg, func(o *s3.Options) { o.UsePathStyle = true })

bucket, key := aws.String(os.Getenv("S3_BUCKET")), aws.String("avatars/ada.png")

client.PutObject(ctx, &s3.PutObjectInput{Bucket: bucket, Key: key, Body: photo})
link, _ := s3.NewPresignClient(client).PresignGetObject(ctx,
    &s3.GetObjectInput{Bucket: bucket, Key: key})  // link.URL: public for 15m`,
      },
    ],
  },
  {
    id: 'vars',
    icon: TuneRoundedIcon,
    color: accent.pink,
    title: 'Config and secrets',
    blurb:
      'Set runtime environment variables and secrets directly from the terminal.',
    snippets: [
      {
        label: 'Terminal',
        lang: 'shell',
        code: `$ freepod var set LOG_LEVEL=debug       # rolls out right away
$ freepod var set STRIPE_KEY --secret   # prompted, never shown again
$ freepod var list
KEY         VALUE     UPDATED           BY
LOG_LEVEL   debug     2026-10-01 11:42  ada@example.com
STRIPE_KEY  <hidden>  2026-10-01 11:43  ada@example.com`,
      },
    ],
  },
  {
    id: 'auth',
    icon: KeyRoundedIcon,
    color: accent.blue,
    title: 'Sign in with Freepod',
    blurb:
      'Need to know who your users are? Turn on authentication and visitors sign in before they reach your app. Your app gets their identity in request headers (X-Freepod-User, X-Freepod-Email), with no login code to write.',
    snippets: [
      {
        label: 'Python',
        lang: 'python',
        code: `# .freepod.json: "auth": {"enabled": true}

@app.get("/")
def home():
    email = request.headers["X-Freepod-Email"]   # verified, signed in
    return f"Hi {email}"`,
      },
      {
        label: 'Node',
        lang: 'js',
        code: `// .freepod.json: "auth": { "enabled": true }

app.get('/', (req, res) => {
  const email = req.get('X-Freepod-Email')   // verified, signed in
  res.send(\`Hi \${email}\`)
})`,
      },
      {
        label: 'Go',
        lang: 'go',
        code: `// .freepod.json: "auth": {"enabled": true}

func home(w http.ResponseWriter, r *http.Request) {
    email := r.Header.Get("X-Freepod-Email")   // verified, signed in
    fmt.Fprintf(w, "Hi %s", email)
}`,
      },
    ],
  },
  {
    id: 'debug',
    icon: TerminalRoundedIcon,
    color: accent.cyan,
    title: 'Logs, shell and database access',
    blurb:
      'Tail logs, open a shell in the running container, or pipe a database dump to your laptop, all securely from the terminal.',
    snippets: [
      {
        label: 'Terminal',
        lang: 'shell',
        code: `$ freepod log -f                       # stream your app's output
$ freepod shell                        # a shell in the running container
$ freepod shell pg_dump > backup.sql   # one-off commands, piped home
$ freepod db proxy                     # your database on localhost:5432`,
      },
    ],
  },
]

export const languageTabs = ['Python', 'Node', 'Go'] as const
