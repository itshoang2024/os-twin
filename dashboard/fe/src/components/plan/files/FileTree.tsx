'use client';

import React, { useState } from 'react';
import { useFileTree, useFileList } from '@/hooks/use-files';
import { FileTreeNode } from '@/types';
import { getFileIconMeta } from './file-icons';

interface FileTreeProps {
  planId: string;
  onSelectFile: (path: string) => void;
  selectedPath: string | null;
}

export default function FileTree({ planId, onSelectFile, selectedPath }: FileTreeProps) {
  const { tree, isLoading, isError } = useFileTree(planId);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set(['.']));

  const toggleExpand = (path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  if (isLoading) return <div className="p-4 text-xs animate-pulse">Loading tree...</div>;
  if (isError) return <div className="p-4 text-xs text-danger">Error loading tree</div>;

  return (
    <div className="flex-1 overflow-y-auto custom-scrollbar p-2">
      <div className="text-[10px] font-bold text-text-faint uppercase tracking-widest mb-2 px-2">
        Project Files
      </div>
      {tree?.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          planId={planId}
          expandedPaths={expandedPaths}
          toggleExpand={toggleExpand}
          onSelectFile={onSelectFile}
          selectedPath={selectedPath}
          level={0}
        />
      ))}
    </div>
  );
}

interface TreeNodeProps {
  node: FileTreeNode;
  planId: string;
  expandedPaths: Set<string>;
  toggleExpand: (path: string) => void;
  onSelectFile: (path: string) => void;
  selectedPath: string | null;
  level: number;
}

function TreeNode({
  node,
  planId,
  expandedPaths,
  toggleExpand,
  onSelectFile,
  selectedPath,
  level,
}: TreeNodeProps) {
  const isExpanded = expandedPaths.has(node.path);
  const isSelected = selectedPath === node.path;
  const isDirectory = node.type === 'directory';
  const iconMeta = getFileIconMeta(node.path || node.name, { isDirectory, isExpanded });

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isDirectory) {
      toggleExpand(node.path);
    } else {
      onSelectFile(node.path);
    }
  };

  return (
    <div className="select-none">
      <div
        onClick={handleClick}
        className={`flex items-center gap-1.5 px-2 py-1 rounded cursor-pointer transition-colors text-xs ${
          isSelected
            ? 'bg-primary/10 text-primary font-medium'
            : 'text-text-muted hover:bg-surface-hover hover:text-text-main'
        }`}
        style={{ paddingLeft: `${level * 12 + 8}px` }}
      >
        <span className={`material-symbols-outlined text-[16px] transition-transform ${
          isExpanded ? 'rotate-0' : '-rotate-90'
        } ${isDirectory ? 'visible' : 'invisible'}`}>
          expand_more
        </span>
        <span
          className={`material-symbols-outlined text-[16px] ${iconMeta.colorClass}`}
          title={iconMeta.label}
          aria-hidden="true"
        >
          {iconMeta.icon}
        </span>
        <span className="truncate">{node.name}</span>
      </div>

      {isDirectory && isExpanded && (
        <div className="overflow-hidden">
          <ChildNodes
            planId={planId}
            path={node.path}
            initialChildren={node.children}
            expandedPaths={expandedPaths}
            toggleExpand={toggleExpand}
            onSelectFile={onSelectFile}
            selectedPath={selectedPath}
            level={level + 1}
          />
        </div>
      )}
    </div>
  );
}

interface ChildNodesProps {
  planId: string;
  path: string;
  initialChildren?: FileTreeNode[];
  expandedPaths: Set<string>;
  toggleExpand: (path: string) => void;
  onSelectFile: (path: string) => void;
  selectedPath: string | null;
  level: number;
}

function ChildNodes({
  planId,
  path,
  initialChildren,
  expandedPaths,
  toggleExpand,
  onSelectFile,
  selectedPath,
  level,
}: ChildNodesProps) {
  // initialChildren !== undefined means the tree endpoint already provided children.
  // initialChildren === undefined means we're past the tree depth limit → lazy-fetch.
  const hasPreloaded = initialChildren !== undefined;
  const shouldFetch = !hasPreloaded;

  const { entries, isLoading } = useFileList(planId, shouldFetch ? path : '');
  
  const nodesToRender: FileTreeNode[] | undefined = hasPreloaded
    ? initialChildren
    : entries?.map(e => ({
        name: e.name,
        type: e.type,
        path: path ? `${path}/${e.name}` : e.name,
        size: e.size,
        extension: e.extension,
        children_count: e.children_count,
        // directories from the listing don't come with children → will lazy-fetch on expand
        children: undefined,
      } as FileTreeNode));

  if (isLoading && shouldFetch) {
    return (
      <div className="py-1" style={{ paddingLeft: `${level * 12 + 24}px` }}>
        <div className="h-4 w-24 bg-border/20 animate-pulse rounded" />
      </div>
    );
  }

  if (!nodesToRender || nodesToRender.length === 0) {
    return (
      <div className="text-[10px] text-text-faint py-1" style={{ paddingLeft: `${level * 12 + 24}px` }}>
        Empty directory
      </div>
    );
  }

  return (
    <>
      {nodesToRender.map((child) => (
        <TreeNode
          key={child.path}
          node={child}
          planId={planId}
          expandedPaths={expandedPaths}
          toggleExpand={toggleExpand}
          onSelectFile={onSelectFile}
          selectedPath={selectedPath}
          level={level}
        />
      ))}
    </>
  );
}
