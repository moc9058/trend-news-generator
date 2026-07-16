'use client';

import { useMemo } from 'react';
import { useTranslations } from 'next-intl';
import {
  Background,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { ResearchEvent, ResearchRun } from '@/lib/types';

/* Mirrors pipeline/app/research/schemas.py LEGACY_PHASE_MAP so runs recorded
   before the R0–R9 → 6-phase consolidation render on the same graph. */
const LEGACY_PHASE: Record<string, string> = {
  R0: 'plan', R1: 'plan', R2: 'gather', R3: 'gather', R4: 'extract',
  R5: 'verify', R6: 'verify', R7: 'write', R7L: 'write', R8: 'review', R9: 'review',
};
const normalize = (phase: string) => LEGACY_PHASE[phase] ?? phase;

const PHASES = ['plan', 'gather', 'extract', 'verify', 'write', 'review'] as const;
type PhaseKey = (typeof PHASES)[number];

/* Actors whose llm_call events roll up into each phase node. The localizer is
   split out into per-language child nodes under write. */
const PHASE_ACTORS: Record<PhaseKey, string[]> = {
  plan: ['planner', 'selector'],
  gather: ['retriever', 'triage'],
  extract: ['extractor'],
  verify: ['verifier'],
  write: ['writer'],
  review: ['critic'],
};

type NodeState = 'pending' | 'running' | 'done' | 'error';

interface FlowNodeData extends Record<string, unknown> {
  label: string;
  sub: string;
  state: NodeState;
  metrics: string[];
  warn: boolean;
}

const STATE_CLS: Record<NodeState, string> = {
  pending: 'border-line bg-surface text-fg-faint',
  running: 'border-accent bg-accent-soft text-fg',
  done: 'border-accent-line bg-surface text-fg',
  error: 'border-red-500/40 bg-red-500/10 text-red-300',
};

const STATE_DOT: Record<NodeState, string> = {
  pending: 'bg-slate-500',
  running: 'bg-accent animate-pulse',
  done: 'bg-accent',
  error: 'bg-red-500',
};

function FlowNode({ data }: NodeProps<Node<FlowNodeData>>) {
  return (
    <div className={`w-[190px] rounded-xl border px-3 py-2 shadow-card ${STATE_CLS[data.state]}`}>
      <Handle type="target" position={Position.Top} id="t" className="!bg-transparent !border-0" />
      <Handle type="target" position={Position.Left} id="l" className="!bg-transparent !border-0" />
      <Handle type="source" position={Position.Left} id="ls" style={{ top: '70%' }}
        className="!bg-transparent !border-0" />
      <Handle type="source" position={Position.Right} id="r" className="!bg-transparent !border-0" />
      <Handle type="source" position={Position.Bottom} id="b" className="!bg-transparent !border-0" />
      <div className="flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATE_DOT[data.state]}`} />
        <span className="font-mono text-xs font-semibold">{data.label}</span>
        {data.warn && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-red-500" title="!" />}
      </div>
      <div className="mt-0.5 truncate text-[10px] leading-4 text-fg-muted">{data.sub}</div>
      {data.metrics.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-x-2 font-mono text-[10px] text-fg-faint">
          {data.metrics.map((m) => <span key={m}>{m}</span>)}
        </div>
      )}
    </div>
  );
}

const NODE_TYPES = { flow: FlowNode };

const fmtCost = (usd: number) => (usd >= 0.0005 ? `$${usd.toFixed(usd >= 1 ? 2 : 3)}` : '');
const fmtTokens = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M tok` : n >= 1000 ? `${Math.round(n / 1000)}k tok` : n > 0 ? `${n} tok` : '';

function buildGraph(
  run: ResearchRun,
  events: ResearchEvent[],
  t: ReturnType<typeof useTranslations<'research'>>,
): { nodes: Node<FlowNodeData>[]; edges: Edge[] } {
  const byPhase = new Map<string, ResearchEvent[]>();
  for (const ev of events) {
    const key = normalize(ev.phase);
    byPhase.set(key, [...(byPhase.get(key) ?? []), ev]);
  }
  const currentPhase = normalize(run.phase);

  const stateFor = (key: PhaseKey): NodeState => {
    const evs = byPhase.get(key) ?? [];
    const started = evs.some((e) => e.action === 'phase_start');
    if (run.status === 'failed' && currentPhase === key) return 'error';
    if (!started) return 'pending';
    if (run.status === 'running' && currentPhase === key) return 'running';
    const lastStart = evs.map((e) => e.action).lastIndexOf('phase_start');
    const endedAfter = evs.slice(lastStart).some((e) => e.action === 'phase_end');
    if (endedAfter) return 'done';
    return run.status === 'running' ? 'running' : 'done';
  };

  const metricsFor = (evs: ResearchEvent[]): string[] => {
    const llm = evs.filter((e) => e.action === 'llm_call');
    const cost = llm.reduce((s, e) => s + (e.costUsd ?? 0), 0);
    const tokens = llm.reduce((s, e) => s + (e.tokensIn ?? 0) + (e.tokensOut ?? 0), 0);
    const out: string[] = [];
    if (llm.length) out.push(`LLM×${llm.length}`);
    const c = fmtCost(cost);
    if (c) out.push(c);
    const tk = fmtTokens(tokens);
    if (tk) out.push(tk);
    return out;
  };

  const nodes: Node<FlowNodeData>[] = [];
  const edges: Edge[] = [];
  const COL = 0;
  const SIDE = 320;
  const STEP = 112;

  nodes.push({
    id: 'harness', type: 'flow', position: { x: COL, y: 0 },
    data: {
      label: 'harness', sub: t('flowHarness'),
      state: run.status === 'running' ? 'running'
        : run.status === 'failed' ? 'error'
          : events.length ? 'done' : 'pending',
      metrics: [], warn: false,
    },
  });

  PHASES.forEach((key, i) => {
    const evs = byPhase.get(key) ?? [];
    const actorEvs = evs.filter((e) => PHASE_ACTORS[key].includes(e.actor));
    nodes.push({
      id: key, type: 'flow', position: { x: COL, y: STEP * (i + 1) },
      data: {
        label: key,
        sub: t(`flowPhase_${key}`),
        state: stateFor(key),
        metrics: metricsFor(actorEvs),
        warn: evs.some((e) => e.ok === false),
      },
    });
  });

  edges.push({ id: 'e-harness-plan', source: 'harness', sourceHandle: 'b', target: 'plan', targetHandle: 't' });
  for (let i = 0; i + 1 < PHASES.length; i += 1) {
    edges.push({
      id: `e-${PHASES[i]}-${PHASES[i + 1]}`,
      source: PHASES[i], sourceHandle: 'b',
      target: PHASES[i + 1], targetHandle: 't',
    });
  }

  // loop-backs: verify→gather (coverage loop), review→write (one corrective rewrite)
  if (run.loops > 0) {
    edges.push({
      id: 'e-loop-gather', source: 'verify', sourceHandle: 'ls',
      target: 'gather', targetHandle: 'l', type: 'smoothstep', animated: true,
      label: `${t('flowLoop')} ×${run.loops}`,
    });
  }
  const writeStarts = (byPhase.get('write') ?? []).filter((e) => e.action === 'phase_start').length;
  const revisions = Math.max(0, writeStarts - 1);
  if (revisions > 0) {
    edges.push({
      id: 'e-loop-write', source: 'review', sourceHandle: 'ls',
      target: 'write', targetHandle: 'l', type: 'smoothstep', animated: true,
      label: `${t('flowRevise')} ×${revisions}`,
    });
  }

  // connector fan-out under gather (actor = connector name on connector_search)
  const searches = (byPhase.get('gather') ?? []).filter((e) => e.action === 'connector_search');
  const connectors = [...new Set(searches.map((e) => e.actor))];
  connectors.forEach((conn, i) => {
    const evs = searches.filter((e) => e.actor === conn);
    const hits = evs.reduce((s, e) => s + (Number(e.detail?.hits) || 0), 0);
    const id = `conn-${conn}`;
    nodes.push({
      id, type: 'flow',
      position: { x: SIDE, y: STEP * 2 + (i - (connectors.length - 1) / 2) * 84 },
      data: {
        label: conn, sub: t('flowConnector'), state: 'done',
        metrics: [t('flowSearches', { count: evs.length }), t('flowHits', { count: hits })],
        warn: evs.some((e) => e.ok === false),
      },
    });
    edges.push({ id: `e-gather-${id}`, source: 'gather', sourceHandle: 'r', target: id, targetHandle: 'l' });
  });

  // per-language localization branches under write
  const langs = run.languages.filter((l) => l !== run.canonicalLanguage);
  const locEvents = (byPhase.get('write') ?? [])
    .filter((e) => e.action === 'llm_call' && e.actor === 'localizer');
  langs.forEach((lang, i) => {
    const evs = locEvents.filter((e) => e.detail?.language === lang);
    const done = evs.length > 0 || stateFor('write') === 'done';
    const id = `loc-${lang}`;
    nodes.push({
      id, type: 'flow',
      position: { x: SIDE, y: STEP * 5 + (i - (langs.length - 1) / 2) * 84 },
      data: {
        label: lang, sub: t('flowLocalize'), state: done ? 'done' : 'pending',
        metrics: metricsFor(evs), warn: evs.some((e) => e.ok === false),
      },
    });
    edges.push({ id: `e-write-${id}`, source: 'write', sourceHandle: 'r', target: id, targetHandle: 'l' });
  });

  return { nodes, edges };
}

export function ResearchFlow({ run, events }: { run: ResearchRun; events: ResearchEvent[] }) {
  const t = useTranslations('research');
  const { nodes, edges } = useMemo(() => buildGraph(run, events, t), [run, events, t]);

  return (
    <div>
      <div className="h-[460px] w-full">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.3}
          maxZoom={1.5}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={18} size={1} color="#262B4A" />
        </ReactFlow>
      </div>
      <div className="flex flex-wrap items-center gap-4 border-t border-line/60 px-5 py-2">
        {(['pending', 'running', 'done', 'error'] as NodeState[]).map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5 text-[11px] text-fg-muted">
            <span className={`h-1.5 w-1.5 rounded-full ${STATE_DOT[s]}`} />
            {t(`flowState_${s}`)}
          </span>
        ))}
      </div>
    </div>
  );
}
