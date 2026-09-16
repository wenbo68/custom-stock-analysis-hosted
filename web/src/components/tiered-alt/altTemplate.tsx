import type { ReactNode } from 'react';

// Fill a uiText template's {name} slots with live nodes; unknown slots
// stay as text so a wording/values mismatch is visible, never silent.
// (Its own file because component files may only export components.)
const TEMPLATE_TOKEN_RE = /(\{\w+\})/g;

export const fillTemplate = (template: string, nodes: Record<string, ReactNode>): ReactNode[] =>
  template.split(TEMPLATE_TOKEN_RE).map((part, index) => {
    const match = /^\{(\w+)\}$/.exec(part);
    const node = match ? nodes[match[1]] : undefined;
    return <span key={index}>{node !== undefined ? node : part}</span>;
  });
