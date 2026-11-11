"use client";
import Link from "next/link";
import { useOptimistic, useTransition } from "react";
import { setStage } from "../actions";
import { STAGES, PIPELINE_BY_KEY } from "@/lib/labels";

type Card = { id: string; title: string; stage: string; pipeline: string; source_key: string; deal_value: number | null; follow_up_at: string | null; organisation: string | null };

export function Board({ cards, editable }: { cards: Card[]; editable: boolean }) {
  const [pending, start] = useTransition();
  const [optimistic, move] = useOptimistic(cards, (state: Card[], m: { id: string; stage: string }) =>
    state.map((c) => (c.id === m.id ? { ...c, stage: m.stage } : c)));

  function drop(id: string, stage: string) {
    if (!editable) return;
    start(async () => {
      move({ id, stage });
      const f = new FormData();
      f.set("id", id);
      f.set("stage", stage);
      await setStage(f);
    });
  }

  return (
    <div className={`flex gap-3 overflow-x-auto pb-4 ${pending ? "opacity-80" : ""}`}>
      {STAGES.filter((s) => s.key !== "archived").map((s) => {
        const col = optimistic.filter((c) => c.stage === s.key);
        return (
          <div key={s.key} className="panel w-64 shrink-0 p-2"
            onDragOver={(e) => editable && e.preventDefault()} onDrop={(e) => drop(e.dataTransfer.getData("text/plain"), s.key)}>
            <div className="mb-2 flex items-center justify-between px-1 text-sm font-semibold">{s.label}<span className="muted text-xs">{col.length}</span></div>
            <div className="space-y-2">
              {col.map((c) => (
                <div key={c.id} draggable={editable} onDragStart={(e) => e.dataTransfer.setData("text/plain", c.id)}
                  className="rounded-lg border line bg-[var(--bg)] p-2 text-sm">
                  <Link href={`/opportunities/${c.id}`} className="line-clamp-2 font-medium hover:underline">{c.title || "(untitled)"}</Link>
                  <div className="muted mt-1 text-xs">{PIPELINE_BY_KEY[c.pipeline]?.short} · {c.source_key}{c.organisation ? ` · ${c.organisation}` : ""}</div>
                  {c.deal_value ? <div className="mt-1 text-xs">£{Number(c.deal_value).toLocaleString("en-GB")}</div> : null}
                  {editable ? (
                    <select aria-label="Move to stage" className="input mt-2 py-1 text-xs" value={c.stage} onChange={(e) => drop(c.id, e.target.value)}>
                      {STAGES.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
                    </select>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
