import Link from '@docusaurus/Link'
import Layout from '@theme/Layout'

const ENTRIES = [
  {
    to: '/apps',
    title: 'Using apps',
    body: 'Run apps from the Freepod catalog: setup, hostnames, file access, product guides.',
  },
  {
    to: '/developers',
    title: 'Developers',
    body: 'Deploy your own code with the freepod CLI: builds, runtime, storage, CLI reference.',
  },
]

export default function Home() {
  return (
    <Layout title="Documentation" description="Freepod documentation">
      <main className="container margin-vert--xl">
        <h1>Freepod documentation</h1>
        <div className="entry-grid">
          {ENTRIES.map((entry) => (
            <Link key={entry.to} to={entry.to} className="entry-card">
              <h2>{entry.title}</h2>
              <p>{entry.body}</p>
            </Link>
          ))}
        </div>
      </main>
    </Layout>
  )
}
