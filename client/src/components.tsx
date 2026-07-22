import type { FormEvent, ReactNode } from "react";
import type { PlantView, ProvenanceRecord, Citation } from "./domain";
import { navigate } from "./routing";

export function Link({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return <a className={className} href={href} onClick={(event) => { event.preventDefault(); navigate(href); }}>{children}</a>;
}

const primary = [
  ["Overview", "/conservatory"], ["My Plants", "/conservatory/plants"],
  ["Search", "/conservatory/search"], ["Scan QR", "/conservatory/scan"],
] as const;
const deferred = [
  ["Reports", "reports"], ["Environment", "environment"], ["Blooms", "blooms"],
  ["Repotting", "repotting"], ["Reminders", "reminders"], ["Media", "media"],
  ["Exports", "exports"], ["Sharing", "sharing"],
] as const;

export function ApplicationShell({ children, onSignOut }: { children: ReactNode; onSignOut(): void }) {
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to main content</a>
    <aside className="sidebar">
      <div className="brand"><span aria-hidden="true">◌</span><div><strong>My Conservatory</strong><small>Orchid Continuum</small></div></div>
      <nav aria-label="Primary navigation"><p className="nav-label">Collection</p>{primary.map(([label, href]) => <Link key={href} href={href}>{label}</Link>)}
        <p className="nav-label">Planned</p>{deferred.map(([label, slug]) => <Link key={slug} href={`/conservatory/${slug}`}>{label}<small>Future</small></Link>)}</nav>
    </aside>
    <div className="workspace">
      <header className="topbar"><div><span className="eyebrow">Private collection workspace</span></div><button className="quiet" onClick={onSignOut}>Sign out</button></header>
      <main id="main-content" tabIndex={-1}>{children}</main>
    </div>
  </div>;
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return <header className="page-header"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{actions && <div className="actions">{actions}</div>}</header>;
}

export function ScientificNameDisplay({ plant, heading = false }: { plant: PlantView; heading?: boolean }) {
  const name = plant.acceptedScientificName || plant.displayName;
  const content = <><i>{name}</i>{plant.authorship && <span className="authorship"> {plant.authorship}</span>}{plant.uncertainIdentification && <span className="uncertainty" title="Identification is uncertain">Identification uncertain</span>}</>;
  return <div className="scientific-name">{heading ? <h1>{content}</h1> : <h3>{content}</h3>}{plant.synonymStatus === "not-supplied" && <small>Accepted-name and synonym status are not supplied by the current backend.</small>}</div>;
}

export function OrchidCard({ plant }: { plant: PlantView }) {
  return <article className="orchid-card"><div className="orchid-thumb" aria-hidden="true">✣</div><ScientificNameDisplay plant={plant}/><p>{plant.notes || "No collection notes."}</p><div className="meta"><span>Added {new Date(plant.collectionMetadata.createdAt).toLocaleDateString()}</span><span>{plant.qrIdentifier ? "QR linked" : "No QR"}</span></div><Link href={`/conservatory/plants/${encodeURIComponent(plant.id)}`} className="stretched">View plant <span aria-hidden="true">→</span></Link></article>;
}

export function PlantHeader({ plant }: { plant: PlantView }) {
  return <header className="plant-header"><div className="plant-mark" aria-hidden="true">✣</div><div><span className="eyebrow">Collection plant</span><ScientificNameDisplay plant={plant} heading/><p>Record {plant.id}</p></div></header>;
}

export function LoadingState({ label = "Loading collection" }: { label?: string }) { return <div className="state" role="status"><span className="spinner" aria-hidden="true"/><h2>{label}</h2><p>Retrieving current data from Calyx.</p></div>; }
export function EmptyState({ title, message, action }: { title: string; message: string; action?: ReactNode }) { return <div className="state"><span className="state-icon" aria-hidden="true">◇</span><h2>{title}</h2><p>{message}</p>{action}</div>; }
export function ErrorState({ error, retry }: { error: Error; retry?(): void }) { return <div className="state error" role="alert"><span className="state-icon" aria-hidden="true">!</span><h2>We couldn’t load this view</h2><p>{error.message}</p>{retry && <button onClick={retry}>Try again</button>}</div>; }

export function SearchField({ value, onChange, onSubmit, label = "Search your collection" }: { value: string; onChange(value: string): void; onSubmit?(): void; label?: string }) {
  return <form className="search-field" role="search" onSubmit={(event: FormEvent) => { event.preventDefault(); onSubmit?.(); }}><label htmlFor="collection-search">{label}</label><div><input id="collection-search" type="search" value={value} onChange={(event) => onChange(event.target.value)} placeholder="Scientific name, synonym, or note"/><button type="submit">Search</button></div></form>;
}

export function FilterPanel({ sort, category, onSort, onCategory }: { sort: string; category: string; onSort(value: "name-asc"|"name-desc"|"newest"|"oldest"): void; onCategory(value: string): void }) {
  return <section className="filters" aria-label="Collection filters"><label>Sort<select value={sort} onChange={(e) => onSort(e.target.value as never)}><option value="name-asc">Name A–Z</option><option value="name-desc">Name Z–A</option><option value="newest">Newest</option><option value="oldest">Oldest</option></select></label><label>Category ID<input value={category} onChange={(e) => onCategory(e.target.value)} placeholder="All categories"/></label></section>;
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage(page: number): void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return <nav className="pagination" aria-label="Collection pages"><button disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button><span>Page {page} of {pages}</span><button disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button></nav>;
}

export function CollectionTable({ plants }: { plants: PlantView[] }) {
  return <div className="table-scroll"><table><caption className="sr-only">Plants in your collection</caption><thead><tr><th scope="col">Plant</th><th scope="col">Notes</th><th scope="col">Added</th><th scope="col">QR</th></tr></thead><tbody>{plants.map((plant) => <tr key={plant.id} onDoubleClick={() => navigate(`/conservatory/plants/${plant.id}`)}><th scope="row"><Link href={`/conservatory/plants/${plant.id}`}>{plant.displayName}</Link></th><td>{plant.notes || "—"}</td><td>{new Date(plant.collectionMetadata.createdAt).toLocaleDateString()}</td><td>{plant.qrIdentifier ? "Linked" : "—"}</td></tr>)}</tbody></table></div>;
}

export function SearchResultCard({ plant }: { plant: PlantView }) { return <OrchidCard plant={plant}/>; }
export function QRDisplay({ value }: { value: string | null }) { return <div className="qr-display"><span aria-hidden="true">▦</span><div><strong>QR identifier</strong><code>{value || "Not assigned"}</code></div></div>; }
export function CitationPanel({ citations }: { citations: readonly Citation[] }) { return <section className="panel"><h2>Citations</h2>{citations.length ? <ol>{citations.map((item) => <li key={`${item.source}-${item.label}`}><strong>{item.label}</strong> — {item.source}</li>)}</ol> : <p>No citations are attached to this collection record.</p>}</section>; }
export function ProvenanceViewer({ records }: { records: readonly ProvenanceRecord[] }) { return <section className="panel"><h2>Provenance</h2><ul className="provenance">{records.map((item) => <li key={`${item.source}-${item.recordId}`}><strong>{item.source}</strong><span>{item.statement}</span><small>Record {item.recordId} · retrieved {new Date(item.retrievedAt).toLocaleString()}</small></li>)}</ul></section>; }
