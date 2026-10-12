import { Background, Controls, ReactFlow, type Edge, type Node } from '@xyflow/react'

/** A thin wrapper around React Flow. Give the parent a `key` to re-fit the view when the data changes. */
export default function FlowGraph({ nodes, edges, height = 340, label, onNodeClick }: {
  nodes: Node[]
  edges: Edge[]
  height?: number
  label: string
  onNodeClick?: (id: string) => void
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="w-full overflow-hidden rounded-lg border border-navy-600 bg-navy-900"
      style={{ height }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        colorMode="dark"
        nodesConnectable={false}
        minZoom={0.2}
        onNodeClick={onNodeClick ? (_, node) => onNodeClick(node.id) : undefined}
      >
        <Background gap={20} color="#1c2842" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}