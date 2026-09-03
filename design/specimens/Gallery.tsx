import { useEffect, useMemo, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { ThemeProvider, useTheme } from '../src/workspace/ThemeProvider';
import type { Density, Theme } from '../src/workspace/ThemeProvider';

export interface Specimen {
  name: string;
  render: () => ReactNode;
}

export interface SpecimenModule {
  title: string;
  specimens: Specimen[];
}

export interface SpecimenGroup {
  /** Source folder — `primitives`, `states`, `research`, `conversation`, `manuscript`, `workspace`. */
  folder: string;
  path: string;
  module: SpecimenModule;
}

export interface GalleryProps {
  groups: SpecimenGroup[];
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
}

const THEMES: Theme[] = ['dark', 'light'];
const DENSITIES: Density[] = ['comfortable', 'compact'];

function Controls({ count }: { count: number }): ReactElement {
  const { theme, density, setTheme, setDensity, prefersReducedMotion } = useTheme();
  return (
    <div className="gallery__controls">
      <fieldset>
        <legend>Theme</legend>
        {THEMES.map((option) => (
          <label key={option}>
            <input
              type="radio"
              name="theme"
              value={option}
              checked={theme === option}
              onChange={() => setTheme(option)}
            />
            {option}
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Density</legend>
        {DENSITIES.map((option) => (
          <label key={option}>
            <input
              type="radio"
              name="density"
              value={option}
              checked={density === option}
              onChange={() => setDensity(option)}
            />
            {option}
          </label>
        ))}
      </fieldset>
      <p className="gallery__motion" data-reduced={prefersReducedMotion ? '' : undefined}>
        {prefersReducedMotion
          ? 'Reduced motion: on — transitions collapse to a single frame.'
          : 'Reduced motion: off'}
      </p>
      <p className="gallery__count">{`${count} specimens`}</p>
    </div>
  );
}

function Frame({ specimen, id }: { specimen: Specimen; id: string }): ReactElement {
  return (
    <figure className="gallery__frame" id={id}>
      <figcaption className="gallery__frame-caption">{specimen.name}</figcaption>
      <div className="gallery__stage">{specimen.render()}</div>
    </figure>
  );
}

/**
 * The specimen gallery: every component in the package, in its main states, in either
 * theme and either density.
 *
 * There is no browser in this workspace, so DOM snapshots are the regression gate and
 * this page is the human one — it is how a person checks that the tokens actually look
 * right together before a surface ships.
 */
export function Gallery({ groups }: GalleryProps): ReactElement {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return groups;
    return groups
      .map((group) => ({
        ...group,
        module: {
          ...group.module,
          specimens: group.module.specimens.filter(
            (specimen) =>
              specimen.name.toLowerCase().includes(needle) ||
              group.module.title.toLowerCase().includes(needle) ||
              group.folder.includes(needle),
          ),
        },
      }))
      .filter((group) => group.module.specimens.length > 0);
  }, [groups, query]);

  const byFolder = useMemo(() => {
    const map = new Map<string, SpecimenGroup[]>();
    for (const group of filtered) {
      const bucket = map.get(group.folder);
      if (bucket) bucket.push(group);
      else map.set(group.folder, [group]);
    }
    return [...map.entries()];
  }, [filtered]);

  const total = filtered.reduce((sum, group) => sum + group.module.specimens.length, 0);

  return (
    <ThemeProvider storageKey="research-harness:design:specimens">
      <GalleryFrame byFolder={byFolder} total={total} query={query} onQuery={setQuery} />
    </ThemeProvider>
  );
}

function GalleryFrame({
  byFolder,
  total,
  query,
  onQuery,
}: {
  byFolder: Array<[string, SpecimenGroup[]]>;
  total: number;
  query: string;
  onQuery: (value: string) => void;
}): ReactElement {
  // The gallery owns the page, so it sets the page background from the canvas token.
  useEffect(() => {
    document.body.classList.add('gallery-body');
    return () => document.body.classList.remove('gallery-body');
  }, []);

  return (
    <div className="gallery">
      <a className="gallery__skip" href="#gallery-main">
        Skip to the specimens
      </a>
      <nav className="gallery__index" aria-label="Specimen index">
        <h1 className="gallery__title">Design System specimens</h1>
        <Controls count={total} />
        <label className="gallery__search">
          Filter
          <input
            type="search"
            value={query}
            placeholder="FileTree, workspace, stale…"
            onChange={(event) => onQuery(event.target.value)}
          />
        </label>
        {byFolder.map(([folder, groups]) => (
          <section key={folder} className="gallery__index-group">
            <h2>{folder}</h2>
            <ul>
              {groups.map((group) => (
                <li key={group.path}>
                  <a href={`#${slug(`${folder}-${group.module.title}`)}`}>{group.module.title}</a>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </nav>

      <main className="gallery__main" id="gallery-main">
        {byFolder.length === 0 ? <p>No specimen matches that filter.</p> : null}
        {byFolder.map(([folder, groups]) => (
          <section key={folder} className="gallery__section" aria-label={folder}>
            <h2 className="gallery__folder">{folder}</h2>
            {groups.map((group) => {
              const id = slug(`${folder}-${group.module.title}`);
              return (
                <section key={group.path} className="gallery__component" id={id}>
                  <h3 className="gallery__component-title">{group.module.title}</h3>
                  <div className="gallery__frames">
                    {group.module.specimens.map((specimen) => (
                      <Frame
                        key={specimen.name}
                        specimen={specimen}
                        id={`${id}-${slug(specimen.name)}`}
                      />
                    ))}
                  </div>
                </section>
              );
            })}
          </section>
        ))}
      </main>
    </div>
  );
}
