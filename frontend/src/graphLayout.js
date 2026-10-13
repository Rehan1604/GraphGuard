import { MarkerType, Position, } from '@xyflow/react'
import { formatMoney } from './format'







export function circlePositions(ids, radius, center = { x: 0, y: 0 }) {
  const out = {}
  ids.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / Math.max(ids.length, 1) - Math.PI / 2
    out[id] = { x: center.x + radius * Math.cos(angle), y: center.y + radius * Math.sin(angle) }
  })
  return out
}

/** Each pattern gets a layout that makes its shape obvious at a glance. */
export function layoutForRule(rule, accounts) {
  if (accounts.length === 0) return { positions: {}, horizontal: false }
  if (rule === 'pass_through_chain') {
    // a line, left to right, in the order the money moved
    return { horizontal: true, positions: Object.fromEntries(accounts.map((id, i) => [id, { x: i * 240, y: 0 }])) }
  }
  if (rule === 'burst' || rule === 'fan') {
    // the account in focus in the middle, everyone else around it
    const [focus, ...others] = accounts
    return {
      horizontal: false,
      positions: { [focus]: { x: 0, y: 0 }, ...circlePositions(others, Math.max(180, others.length * 40)) },
    }
  }
  return { horizontal: false, positions: circlePositions(accounts, Math.max(130, accounts.length * 55)) }
}

const NODE_STYLE = {
  background: '#131c30',
  color: '#e2e8f0',
  border: '1px solid #3b4d75',
  borderRadius: 10,
  fontSize: 12,
  padding: '6px 10px',
} 

const EMERALD = '#34d399'
const AMBER = '#fbbf24'

export function buildEvidenceGraph(alert) {
  const ids = [...alert.accounts]
  for (const tx of alert.evidence) {
    for (const account of [tx.source_account_id, tx.target_account_id]) if (!ids.includes(account)) ids.push(account)
  }
  const { positions, horizontal } = layoutForRule(alert.rule, ids)

  // Merge repeated transfers between the same two accounts into one arrow.
  const groups = new Map()
  for (const tx of alert.evidence) {
    const key = `${tx.source_account_id}->${tx.target_account_id}`
    const group = groups.get(key)
    if (group) {
      group.count += 1
      group.total += Number(tx.amount)
    } else {
      groups.set(key, {
        source: tx.source_account_id, target: tx.target_account_id, count: 1,
        total: Number(tx.amount), currency: tx.currency, step: groups.size + 1,
      })
    }
  }
  const numbered = alert.rule === 'pass_through_chain' || alert.rule === 'cycle'

  const edges = [...groups.entries()].map(([key, g]) => {
    const money = formatMoney(String(g.total), g.currency)
    const text = g.count > 1 ? `${g.count} transfers, ${money}` : money
    return {
      id: key,
      source: g.source,
      target: g.target,
      label: numbered ? `${g.step}. ${text}` : text,
      markerEnd: { type: MarkerType.ArrowClosed, color: EMERALD },
      style: { stroke: EMERALD, strokeWidth: 1.5 },
      labelStyle: { fill: '#cbd5e1', fontSize: 11 },
      labelBgStyle: { fill: '#0d1424' },
    }
  })

  const focus = alert.rule === 'burst' || alert.rule === 'fan' ? alert.accounts[0] : undefined
  const nodes = ids.map((id) => ({
    id,
    position: positions[id] ?? { x: 0, y: 0 },
    data: { label: id },
    sourcePosition: horizontal ? Position.Right : Position.Bottom,
    targetPosition: horizontal ? Position.Left : Position.Top,
    style: { ...NODE_STYLE, ...(id === focus ? { border: `2px solid ${EMERALD}` } : {}) },
  }))
  return { nodes, edges }
}

/** The whole account network. Amber outline = this account is part of an open alert. */
export function buildNetworkGraph(data, selected) {
  const ids = data.nodes.map((n) => n.id)
  const positions = circlePositions(ids, Math.max(160, ids.length * 14))
  const nodes = data.nodes.map((n) => ({
    id: n.id,
    position: positions[n.id],
    data: { label: n.id },
    style: {
      ...NODE_STYLE,
      fontSize: 10,
      padding: '3px 6px',
      border:
        n.id === selected ? `2px solid ${EMERALD}` : n.open_alerts > 0 ? `2px solid ${AMBER}` : '1px solid #3b4d75',
    },
  }))
  const edges = data.edges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    markerEnd: { type: MarkerType.ArrowClosed, color: '#64748b' },
    style: { stroke: '#64748b', strokeWidth: Math.min(1 + Math.sqrt(e.transaction_count), 4) },
  }))
  return { nodes, edges }
}