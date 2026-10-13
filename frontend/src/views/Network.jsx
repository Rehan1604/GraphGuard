import { useMemo, useState } from 'react'
import { fetchGraph } from '../api'
import FlowGraph from '../components/FlowGraph'
import { Async, Card, Empty, buttonClass, inputClass } from '../components/ui'
import { formatMoney } from '../format'
import { buildNetworkGraph } from '../graphLayout'
import { useFetch } from '../hooks'


export default function Network({ version, onSearchAccount }) {
  const [limit, setLimit] = useState(300)
  const [selected, setSelected] = useState(null)
  const state = useFetch(() => fetchGraph(limit), [limit, version])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="graph-limit" className="mb-1 block text-xs text-slate-400">Transactions to include</label>
          <select id="graph-limit" className={`${inputClass} w-44`} value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            <option value={100}>Latest 100</option>
            <option value={300}>Latest 300</option>
            <option value={1000}>Latest 1,000</option>
          </select>
        </div>
        <p className="text-sm text-slate-400">
          <span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm border-2 border-amber-400 align-middle" aria-hidden="true" />
          amber outline = account is part of an open alert. Click an account for details.
        </p>
      </div>

      <Async state={state}>
        {(data) =>
          data.nodes.length === 0 ? (
            <Empty title="The graph is empty">No transactions yet. Start the simulation from the top bar.</Empty>
          ) : (
            <NetworkBody data={data} selected={selected} onSelect={setSelected} onSearchAccount={onSearchAccount} />
          )
        }
      </Async>
    </div>
  )
}

function NetworkBody({ data, selected, onSelect, onSearchAccount }




) {
  const graph = useMemo(() => buildNetworkGraph(data, selected), [data, selected])
  const node = data.nodes.find((n) => n.id === selected)
  const outgoing = data.edges.filter((e) => e.source === selected)
  const incoming = data.edges.filter((e) => e.target === selected)

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
      <div>
        <FlowGraph key={data.nodes.length} {...graph} height={560} label="Account network" onNodeClick={onSelect} />
        <p className="mt-2 text-xs text-slate-400">
          {data.nodes.length} accounts, {data.edges.length} links, {data.transactions_considered} transfers considered.
          Thicker arrows mean more transfers.
        </p>
      </div>
      <Card title="Account">
        {!node ? (
          <p className="text-sm text-slate-400">Click an account in the graph.</p>
        ) : (
          <div className="space-y-3 text-sm">
            <div>
              <div className="font-mono text-slate-100">{node.id}</div>
              <div className="text-slate-400">{node.name} | {node.account_type}</div>
            </div>
            <div>Open alerts involving it: <strong>{node.open_alerts}</strong></div>
            <div>
              <div className="text-xs uppercase tracking-wider text-slate-400">Sends to ({outgoing.length})</div>
              <ul className="mt-1 space-y-0.5 font-mono text-xs">
                {outgoing.slice(0, 6).map((e) => (
                  <li key={e.target}>{e.target} <span className="text-slate-400">x{e.transaction_count}, {formatMoney(e.total_amount, e.currency)}</span></li>
                ))}
              </ul>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider text-slate-400">Receives from ({incoming.length})</div>
              <ul className="mt-1 space-y-0.5 font-mono text-xs">
                {incoming.slice(0, 6).map((e) => (
                  <li key={e.source}>{e.source} <span className="text-slate-400">x{e.transaction_count}, {formatMoney(e.total_amount, e.currency)}</span></li>
                ))}
              </ul>
            </div>
            <button className={buttonClass} onClick={() => onSearchAccount(node.id)}>Show alerts for this account</button>
          </div>
        )}
      </Card>
    </div>
  )
}