import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

interface ScopeListProps {
  grantedScopes: string[];
  requestedScopes?: string[];
}

export function ScopeList({ grantedScopes, requestedScopes = [] }: ScopeListProps) {
  const [expanded, setExpanded] = useState(false);
  const missingScopes = requestedScopes.filter((scope) => !grantedScopes.includes(scope));

  if (!grantedScopes.length && !missingScopes.length) {
    return null;
  }

  return (
    <div className="mt-1 text-xs text-text-secondary">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="inline-flex items-center gap-1 hover:text-text-body"
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span>{grantedScopes.length} scopes granted</span>
      </button>
      {missingScopes.length > 0 && (
        <div className="mt-1 text-amber-700">Missing {missingScopes.length} requested scopes</div>
      )}
      {expanded && (
        <div className="mt-2 flex flex-wrap gap-1">
          {grantedScopes.map((scope) => (
            <span key={scope} className="rounded border border-border-gray bg-bg-gray px-1.5 py-0.5 font-mono text-[10px]">
              {scope}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
