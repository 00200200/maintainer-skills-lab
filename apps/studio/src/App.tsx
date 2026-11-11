import { useMemo, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { formatNumber as number, formatPercent, providerNames } from './profile';
import type { Profile } from './profile';
import { useProfile } from './useProfile';

type Tab = 'skills' | 'agents' | 'providers';
type IconName = Tab | 'refresh' | 'search' | 'arrow' | 'info';
const tabs: Tab[] = ['skills', 'agents', 'providers'];
const budgets = [8_000, 32_000, 128_000, 200_000, 1_000_000];
const budgetLabels = ['8k', '32k', '128k', '200k', '1M'];

function Icon({ name, spin = false }: { name: IconName; spin?: boolean }) {
  const paths: Record<IconName, string> = {
    skills: 'M4 5h6v6H4z M14 5h6v6h-6z M4 15h6v6H4z M14 15h6v6h-6z',
    agents: 'M16 21v-2a4 4 0 0 0-8 0v2 M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M19 9v6 M16 12h6',
    providers: 'M8 8H4v12h12v-4 M10 4h10v10H10z',
    refresh: 'M20 7v5h-5 M4 17v-5h5 M6 7a7 7 0 0 1 12-2l2 3 M18 17a7 7 0 0 1-12 2l-2-3',
    search: 'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
    arrow: 'M5 12h14 M13 6l6 6-6 6',
    info: 'M12 11v6 M12 7v1 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  };
  return <svg aria-hidden="true" className={`icon ${spin ? 'animate-spin' : ''}`} viewBox="0 0 24 24"
    fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <path d={paths[name]} />
  </svg>;
}

interface Row {
  id: string;
  name: string;
  tokens: number;
  subtitle: string;
  secondary: string;
  status: string;
  warnings: string[];
  metrics: { label: string; value: number }[];
  note: string;
}

function rowsFor(profile: Profile, tab: Tab): Row[] {
  if (tab === 'skills') return profile.skills.map((skill) => ({
    id: skill.name, name: skill.name, tokens: skill.tokens,
    subtitle: 'Source skill · all files', secondary: number(skill.desc_tokens),
    status: skill.warnings.length ? `${skill.warnings.length} warnings` : 'No warnings',
    warnings: skill.warnings,
    metrics: [
      { label: 'All skill files', value: skill.tokens },
      { label: 'SKILL.md incl. frontmatter', value: skill.body_tokens },
      { label: 'Description tokens', value: skill.desc_tokens },
      { label: 'Description characters', value: skill.desc_characters },
    ],
    note: 'All files include SKILL.md, scripts and references. SKILL.md and description counts overlap with the total; do not add them. Warning text is returned unchanged by kit.',
  }));
  if (tab === 'agents') return profile.agents.map((agent) => ({
    id: agent.name, name: agent.name, tokens: agent.total_tokens,
    subtitle: `${agent.mode} mode · ${agent.referenced_skills_count} skill references`,
    secondary: number(agent.instructions_tokens), status: agent.mode, warnings: [],
    metrics: [
      { label: 'Profile total tokens', value: agent.total_tokens },
      { label: 'Instruction tokens', value: agent.instructions_tokens },
      { label: 'Skill / manifest tokens', value: agent.referenced_skills_tokens },
      { label: 'Referenced skill count', value: agent.referenced_skills_count },
    ],
    note: 'Total is instructions plus referenced skill content or a lazy manifest, as computed by kit. Subagent instructions include the handoff protocol. Profiles can reference the same skills; their totals are not additive.',
  }));
  return Object.entries(profile.targets).map(([id, provider]) => ({
    id, name: providerNames[id] ?? id, tokens: provider.total_tokens,
    subtitle: `${id} · generated export`, secondary: number(provider.files), status: 'Export bundle', warnings: [],
    metrics: [{ label: 'Export token estimate', value: provider.total_tokens }, { label: 'Export files', value: provider.files }],
    note: 'Tokens cover all generated files for this provider, including expanded agent instructions. Provider exports share source content. Do not sum bundles or add them to source skill counts.',
  }));
}

function BudgetComparison({ row, budget }: { row: Row; budget: number }) {
  const fraction = Math.min(row.tokens / budget, 1);
  const circumference = 2 * Math.PI * 52;
  return <aside className="detail-card" aria-label="Selected item details">
    <div className="eyebrow">Reference comparison</div>
    <h3 className="break-words">{row.name}</h3>
    <p className="muted text-sm">{row.subtitle}</p>
    <div className="budget-ring">
      <svg viewBox="0 0 128 128" aria-hidden="true">
        <circle cx="64" cy="64" r="52" className="ring-track" />
        <circle cx="64" cy="64" r="52" className={row.tokens > budget ? 'ring-value over' : 'ring-value'}
          strokeDasharray={`${fraction * circumference} ${circumference}`} />
      </svg>
      <div><strong>{formatPercent(row.tokens, budget)}<span>%</span></strong><small>of reference budget</small></div>
    </div>
    <p className="text-center text-sm muted">{number(row.tokens)} / {number(budget)} tokens</p>
    {row.tokens > budget && <p className="over-budget">Estimate exceeds the reference budget</p>}
    <dl className="detail-metrics">
      {row.metrics.map(({ label, value }) => <div key={label}><dt>{label}</dt><dd>{number(value)}</dd></div>)}
    </dl>
    {row.warnings.length > 0 && <ul className="warning-list" aria-label="Profiler warnings">
      {row.warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}
    </ul>}
    <p className="detail-note">{row.note}</p>
    <p className="detail-note font-semibold">Static file comparison, not a measurement of an agent session.</p>
  </aside>;
}

function ComparisonChart({ rows, selected, onSelect }: {
  rows: Row[]; selected: string; onSelect: (id: string) => void;
}) {
  const visible = rows.slice(0, 8);
  const maximum = Math.max(1, ...visible.map((row) => row.tokens));
  return <section className="chart-card" aria-labelledby="chart-title">
    <div className="flex flex-wrap justify-between items-start gap-3">
      <div><h3 id="chart-title">Token comparison</h3><p className="muted text-sm mt-1">First {visible.length} results in the current order. Select an item to inspect.</p></div>
      <span className="micro-label">Independent estimates</span>
    </div>
    <div className="chart-bars">
      {visible.map((row) => <button type="button" key={row.id} className={`chart-row ${selected === row.id ? 'selected' : ''}`}
        onClick={() => onSelect(row.id)} aria-pressed={selected === row.id}
        title={`${row.name}: ${number(row.tokens)} tokens`}>
        <span className="chart-label">{row.name}</span>
        <span className="bar-track"><span className="bar-value" style={{ width: `${row.tokens / maximum * 100}%` }} /></span>
        <span className="tabular-nums chart-number">{number(row.tokens)}</span>
      </button>)}
    </div>
    <div className="chart-axis"><span>0 tokens</span><span>{number(maximum)} tokens</span></div>
    <p className="muted text-xs mt-4">Bars scale to the largest visible item. Each bar is a separate comparison, never a combined total.</p>
  </section>;
}

export default function App() {
  const [tab, setTab] = useState<Tab>('skills');
  const [budget, setBudget] = useState(128_000);
  const [interval, setInterval] = useState(30);
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('tokens-desc');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { profile, loading, error, updatedAt, refresh } = useProfile(interval);
  const heuristic = profile?.encoding.toLowerCase().includes('heuristic') ?? false;
  const entries = useMemo(() => profile ? rowsFor(profile, tab) : [], [profile, tab]);
  const rows = useMemo(() => {
    const search = query.trim().toLowerCase();
    return entries.filter((row) => `${row.name} ${row.id} ${row.subtitle} ${row.warnings.join(' ')}`.toLowerCase().includes(search))
      .sort((a, b) => {
        const byName = a.name.localeCompare(b.name);
        if (sort === 'name-asc') return byName;
        if (sort === 'name-desc') return -byName;
        return (sort === 'tokens-asc' ? a.tokens - b.tokens : b.tokens - a.tokens) || byName;
      });
  }, [entries, query, sort]);
  const selected = rows.find((row) => row.id === selectedId) ?? rows[0];
  const counts = profile ? {
    skills: profile.summary.skills_count, agents: profile.summary.agents_count,
    providers: Object.keys(profile.targets).length,
  } : null;

  function switchTab(next: Tab) { setTab(next); setQuery(''); setSelectedId(null); }
  function tabKeys(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    switchTab(tabs[next]);
    document.getElementById(`tab-${tabs[next]}`)?.focus();
  }

  return <div className="studio-shell">
    <a className="skip-link" href="#main">Skip to dashboard</a>
    <aside className="sidebar">
      <a href="#main" className="brand"><img src="/favicon.svg" width="38" height="38" alt="" /><span>Maintainer<span className="brand-sub">STUDIO</span></span></a>
      <div className="workspace-label">WORKSPACE <span>v1</span></div>
      <nav aria-label="Library navigation">
        {tabs.map((value) => <button key={value} type="button" className={`nav-item ${tab === value ? 'active' : ''}`}
          onClick={() => switchTab(value)} aria-label={`Show ${value}`} aria-current={tab === value ? 'page' : undefined}>
          <Icon name={value} /><span className="capitalize">{value}</span><span className="nav-count">{counts?.[value] ?? '—'}</span>
        </button>)}
      </nav>
      <div className="sidebar-note"><span className="local-dot" />Local workspace
        <p>Your library stays on this machine. Read-only exploration. No telemetry.</p>
      </div>
      <div className="sidebar-bottom"><span className="avatar">ML</span><div>Maintainer Skills Lab<small>Independent workflow library</small></div></div>
    </aside>

    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb">Workspace <span>/</span> <strong>Library explorer</strong></div>
        <span className="local-badge"><span className="local-dot" /> Local only</span>
      </header>
      <main id="main" className="main-content" tabIndex={-1}>
        <section className="page-heading">
          <div><div className="eyebrow">YOUR LIBRARY, AT A GLANCE</div><h1>Library explorer<span>.</span></h1>
            <p className="muted mt-2">Understand your workflows. Make context a deliberate choice.</p></div>
          <button type="button" className="button primary" onClick={() => void refresh()} disabled={loading}>
            <Icon name="refresh" spin={loading} />{loading ? 'Refreshing…' : 'Refresh snapshot'}
          </button>
        </section>

        <div className="snapshot-controls">
          <div className="flex flex-wrap items-center gap-3">
            <span className={`estimate-badge ${heuristic ? 'heuristic' : ''}`}>{profile ? heuristic ? '≈ Heuristic estimates' : 'Tokenizer estimates' : 'Waiting for profile'}</span>
            <span className="snapshot-time" role="status" aria-live="polite">{loading ? 'Reading local library…' : updatedAt ? `${error ? 'Last successful snapshot' : 'Updated'} ${updatedAt.toLocaleTimeString()}` : 'No snapshot yet'}</span>
          </div>
          <label className="inline-label">Auto-refresh<select value={interval} onChange={(event) => setInterval(Number(event.target.value))}>
            <option value={0}>Off</option><option value={15}>Every 15s</option><option value={30}>Every 30s</option><option value={60}>Every 60s</option>
          </select></label>
        </div>

        {error && <div className="error-banner" role="alert"><div><strong>Could not refresh the profile</strong><p>{error} {profile ? 'Showing the last successful snapshot.' : 'Start the local Python API server and try again.'}</p></div><button className="button" type="button" disabled={loading} onClick={() => void refresh()}>Try again</button></div>}

        {!profile && loading && <div className="loading-state" role="status"><div className="skeleton-grid" aria-hidden="true">{[0, 1, 2, 3].map((key) => <div className="skeleton" key={key} />)}</div><p>Building a fresh view of your local library…</p></div>}

        {profile && <>
          <section className="metrics-grid" aria-label="Library summary">
            {[
              ['Skill file tokens', number(profile.summary.skills_total_tokens), `${profile.summary.skills_count} source skills · all supporting files`, '01'],
              ['Agent profiles', number(profile.summary.agents_count), 'Independent profiles; shared skills may overlap', '02'],
              ['Names-only floor', number(profile.summary.names_only_floor_tokens), 'Context baseline using skill names only', '03'],
              ['Description overhead', number(profile.summary.descriptions_ceiling_tokens), 'Separate context baseline, not an extra total', '04'],
            ].map(([label, value, caption, index]) => <article className="metric-card" key={label}><div className="flex justify-between gap-2"><h2>{label}</h2><span>{index}</span></div><strong>{value}</strong><p>{caption}</p></article>)}
          </section>

          <div className="semantics-note"><Icon name="info" /><p>These are <strong>static library estimates</strong>, not session usage. Skills, agents and provider exports overlap. Compare them independently.</p></div>

          <section className="inventory" aria-label="Library inventory">
            <div className="inventory-heading">
              <div role="tablist" aria-label="Profile categories" className="tabs">
                {tabs.map((value, index) => <button type="button" key={value} id={`tab-${value}`} role="tab" aria-selected={tab === value}
                  aria-controls="inventory-panel" tabIndex={tab === value ? 0 : -1} onKeyDown={(event) => tabKeys(event, index)} onClick={() => switchTab(value)}>
                  <span className="capitalize">{value}</span><span className="tab-count">{counts?.[value]}</span>
                </button>)}
              </div>
              <span className="micro-label">READ-ONLY INVENTORY</span>
            </div>

            <div role="tabpanel" id="inventory-panel" aria-labelledby={`tab-${tab}`}>
              <div className="inventory-controls">
                <label className="search-field"><Icon name="search" /><span className="sr-only">Search {tab}</span><input type="search" placeholder={`Search ${tab}…`} value={query} onChange={(event) => setQuery(event.target.value)} /></label>
                <label className="control-label">Sort by<select value={sort} onChange={(event) => setSort(event.target.value)}><option value="tokens-desc">Tokens: high to low</option><option value="tokens-asc">Tokens: low to high</option><option value="name-asc">Name: A–Z</option><option value="name-desc">Name: Z–A</option></select></label>
                <label className="control-label">Reference budget<select value={budget} onChange={(event) => setBudget(Number(event.target.value))}>
                  {budgets.map((value, index) => <option value={value} key={value}>{budgetLabels[index]} context · {number(value)}</option>)}
                </select></label>
              </div>

              {rows.length === 0 ? <div className="empty-state"><Icon name={tab} /><h3>{query.trim() ? 'No matching results' : `No ${tab} in this snapshot`}</h3><p>{query.trim() ? 'Try another name, mode or warning.' : 'The API returned an empty collection for this category.'}</p>{query && <button type="button" className="button" onClick={() => setQuery('')}>Clear search</button>}</div> : <>
                <div className="comparison-grid"><ComparisonChart rows={rows} selected={selected.id} onSelect={setSelectedId} /><BudgetComparison row={selected} budget={budget} /></div>
                <div className="table-caption"><h3 className="capitalize">{tab} inventory</h3><span>{rows.length} of {entries.length} results</span></div>
                <div className="table-scroll"><table><caption className="sr-only">{tab} token estimates. Select a name to inspect details above.</caption><thead><tr><th scope="col">Name</th><th scope="col">{tab === 'skills' ? 'All file tokens' : tab === 'agents' ? 'Profile tokens' : 'Export tokens'}</th><th scope="col">{tab === 'skills' ? 'Description tokens' : tab === 'agents' ? 'Instruction tokens' : 'Export files'}</th><th scope="col">{tab === 'skills' ? 'Warnings' : 'Scope'}</th><th scope="col">% of reference budget</th></tr></thead>
                  <tbody>{rows.map((row) => <tr key={row.id} className={selected.id === row.id ? 'selected' : ''}><td><button type="button" className="item-button" onClick={() => setSelectedId(row.id)} aria-pressed={selected.id === row.id}><span className={`item-symbol ${tab}`}><Icon name={tab} /></span><span><strong>{row.name}</strong><small>{row.subtitle}</small></span><Icon name="arrow" /></button></td><td className="token-cell">{number(row.tokens)}</td><td className="tabular-nums">{row.secondary}</td><td><span className={`status-pill ${row.warnings.length ? 'warning' : ''}`} title={row.warnings.join('; ')}>{row.status}</span></td><td className="tabular-nums">{formatPercent(row.tokens, budget)}%{row.tokens > budget && <span className="over-indicator"> over</span>}</td></tr>)}</tbody>
                </table></div>
              </>}
            </div>
          </section>
          <footer className="page-footer"><span>Maintainer Skills Lab <span className="footer-separator">/</span> Local library inspector</span><span className="encoding-label">{profile.encoding}</span></footer>
        </>}
      </main>
    </div>
  </div>;
}
