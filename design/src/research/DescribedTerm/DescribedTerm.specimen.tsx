import type { ReactNode } from 'react';
import { researchLabel, researchMeaning } from '../labels';
import { DescribedTerm } from './DescribedTerm';

export const title = 'DescribedTerm';

export const specimens: Array<{ name: string; render: () => ReactNode }> = [
  {
    name: 'A metadata fact, with its meaning one press away',
    render: () => (
      <dl style={{ display: 'flex', gap: 24, margin: 0 }}>
        {(
          [
            ['Type', 'evidenceType', 'experimental_result'],
            ['Strength', 'evidenceStrength', 'direct'],
            ['Origin', 'evidenceOrigin', 'source_observed'],
          ] as const
        ).map(([label, vocabulary, value]) => (
          <div key={label}>
            <dt className="rh-text-label">{label}</dt>
            <dd style={{ margin: 0 }}>
              <DescribedTerm description={researchMeaning(vocabulary, value) ?? ''}>
                {researchLabel(vocabulary, value)}
              </DescribedTerm>
            </dd>
          </div>
        ))}
      </dl>
    ),
  },
];
