import { useId, useMemo, useState } from "react";
import { getScene, sceneTargets } from "./model";
import type { StoryDraft } from "./types";

export function RouteMap({ story, selected, onSelect }: {
  story: StoryDraft; selected: string; onSelect: (id: string) => void;
}) {
  const marker = "route-arrow-" + useId().replace(/:/g, "");
  const [zoom, setZoom] = useState(1);
  const layout = useMemo(() => {
    const pending = [{ id: story.entry, depth: 0 }], seen = new Set<string>();
    const ordered: Array<{ id: string; depth: number }> = [];
    while (pending.length && ordered.length < 250) {
      const item = pending.shift()!;
      const node = getScene(story, item.id);
      if (!node || seen.has(item.id)) continue;
      seen.add(item.id); ordered.push(item);
      for (const target of sceneTargets(node)) if (!seen.has(target)) pending.push({ id: target, depth: item.depth + 1 });
    }
    for (const id of Object.keys(story.nodes)) {
      if (ordered.length >= 250) break;
      if (!seen.has(id)) { seen.add(id); ordered.push({ id, depth: 0 }); }
    }
    const counts = new Map<number, number>();
    const positions = new Map<string, { x: number; y: number }>();
    for (const item of ordered) {
      const column = Math.min(item.depth, 5), row = counts.get(column) ?? 0;
      counts.set(column, row + 1);
      positions.set(item.id, { x: 64 + column * 250, y: 40 + row * 110 });
    }
    const edges: Array<{ from: string; to: string; label: string; lane: number; lanes: number }> = [];
    let omittedEdges = 0;
    for (const { id } of ordered) {
      const node = getScene(story, id)!;
      sceneTargets(node).forEach((to, index) => {
        if (!positions.has(to)) return;
        if (edges.length >= 1000) { omittedEdges += 1; return; }
        const label = node.type === "choice" ? node.options[index].text.slice(0, 24)
          : node.type === "branch" ? index === 0 ? "Matches" : "Otherwise" : "";
        edges.push({ from: id, to, label, lane: index, lanes: sceneTargets(node).length });
      });
    }
    return { ordered, positions, edges, omittedEdges,
      width: Math.max(440, ...[...positions.values()].map(point => point.x + 260)),
      height: Math.max(320, ...[...positions.values()].map(point => point.y + 110)) };
  }, [story]);
  return <section className="studio-form">
    <div className="studio-section-heading"><h2>Route map</h2><div className="studio-actions">
      <button type="button" className="studio-secondary" aria-label="Zoom out"
        disabled={zoom <= 0.65} onClick={() => setZoom(value => Math.max(0.65, value - 0.15))}>−</button>
      <span>{Math.round(zoom * 100)}%</span>
      <button type="button" className="studio-secondary" aria-label="Zoom in"
        disabled={zoom >= 1.45} onClick={() => setZoom(value => Math.min(1.45, value + 0.15))}>+</button>
    </div></div>
    <p className="studio-hint">Open a scene to edit it. These are structural links; conditions decide which paths are available during play.</p>
    {Object.keys(story.nodes).length > 250 && <p role="status" className="studio-notice">
      Showing 250 scenes. Use the scene list to reach the remaining scenes.</p>}
    {layout.omittedEdges > 0 && <p role="status" className="studio-notice">Showing 1,000 connections. Open a scene to inspect all its destinations.</p>}
    <div className="studio-map" role="region" aria-label="Scrollable route map" tabIndex={0}>
      <svg role="group" aria-label="Scene connections" viewBox={`0 0 ${layout.width} ${layout.height}`}
        width={layout.width * zoom} height={layout.height * zoom}>
        <defs><marker id={marker} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0 0L8 4L0 8z" fill="#4e6577" /></marker></defs>
        {layout.edges.map((edge, index) => {
          const from = layout.positions.get(edge.from)!, to = layout.positions.get(edge.to)!;
          const offset = 12 + 48 * (edge.lane + 1) / (edge.lanes + 1);
          const x1 = from.x + 190, y1 = from.y + offset, x2 = to.x, y2 = to.y + offset;
          return <g key={index}><path d={`M${x1} ${y1} C${x1 + 50} ${y1},${x2 - 50} ${y2},${x2} ${y2}`}
            fill="none" stroke="#4e6577" strokeWidth="1.5" markerEnd={`url(#${marker})`} />
            {edge.label && <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 8}
              className="studio-map-edge-label">{edge.label}</text>}</g>;
        })}
        {layout.ordered.map(({ id }) => {
          const point = layout.positions.get(id)!, node = getScene(story, id)!;
          return <g key={id} transform={`translate(${point.x} ${point.y})`} role="button" tabIndex={0}
            aria-label={`Open scene ${id}`} className={`studio-map-node ${selected === id ? "selected" : ""}`}
            onClick={() => onSelect(id)} onKeyDown={event => {
              if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(id); }
            }}><rect width="190" height="72" rx="8" />
            <text x="14" y="22" className="studio-map-id">{id.slice(0, 21)}</text>
            <text x="14" y="43">{"text" in node ? node.text.slice(0, 23) : node.type === "set" ? "Change story state" : node.type === "stage" ? "Change the stage" : "Check a condition"}</text>
            <text x="14" y="61" className="studio-map-type">{node.type}{id === story.entry ? " · starts here" : ""}</text>
          </g>;
        })}
      </svg>
    </div>
  </section>;
}
