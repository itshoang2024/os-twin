'use client';

import { useState, useRef, useEffect, useMemo } from 'react';
import useSWR from 'swr';
import { Skill } from '@/types';

interface SkillChipInputProps {
  selectedSkillRefs: string[];
  onChange: (skillRefs: string[]) => void;
}

const CATEGORY_LABELS: Record<string, string> = {
  implementation: 'Implementation',
  review: 'Review',
  testing: 'Testing',
  writing: 'Writing',
  analysis: 'Analysis',
  compliance: 'Compliance',
  triage: 'Triage',
};

const TRUST_COLORS: Record<string, { bg: string; text: string }> = {
  core: { bg: 'bg-emerald-100', text: 'text-emerald-700' },
  verified: { bg: 'bg-blue-100', text: 'text-blue-700' },
  experimental: { bg: 'bg-amber-100', text: 'text-amber-700' },
};

export default function SkillChipInput({ selectedSkillRefs, onChange }: SkillChipInputProps) {
  const { data: allSkills = [], isLoading } = useSWR<Skill[]>('/skills');
  const [isOpen, setIsOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const dropdownRef = useRef<HTMLDivElement>(null);

  const selectedSkills = useMemo(
    () => allSkills.filter(s => selectedSkillRefs.includes(s.name)),
    [allSkills, selectedSkillRefs],
  );
  const selectedSkillNames = new Set(selectedSkills.map(s => s.name));
  const missingSelectedSkillRefs = selectedSkillRefs.filter(ref => !selectedSkillNames.has(ref));
  const availableSkills = useMemo(
    () => allSkills.filter(s =>
      !selectedSkillRefs.includes(s.name) &&
      (s.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
       s.description.toLowerCase().includes(searchTerm.toLowerCase()))
    ),
    [allSkills, searchTerm, selectedSkillRefs],
  );

  // Group available skills by category
  const groupedSkills = useMemo(() => {
    const groups: Record<string, Skill[]> = {};
    for (const skill of availableSkills) {
      const cat = skill.category || 'other';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(skill);
    }
    // Sort categories by the defined order
    const orderedKeys = Object.keys(CATEGORY_LABELS);
    const sortedEntries = Object.entries(groups).sort(([a], [b]) => {
      const ia = orderedKeys.indexOf(a);
      const ib = orderedKeys.indexOf(b);
      return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
    });
    return sortedEntries;
  }, [availableSkills]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const toggleSkill = (skillName: string) => {
    if (selectedSkillRefs.includes(skillName)) {
      onChange(selectedSkillRefs.filter(ref => ref !== skillName));
    } else {
      onChange([...selectedSkillRefs, skillName]);
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <div 
        className="flex flex-wrap gap-2 p-2 min-h-[44px] rounded-lg border transition-all cursor-text focus-within:ring-2 focus-within:ring-primary/20"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
        onClick={() => setIsOpen(true)}
      >
        {selectedSkills.map(skill => (
          <span 
            key={skill.id}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold animate-in zoom-in-95"
            style={{ background: 'var(--color-primary-muted)', color: 'var(--color-primary)' }}
          >
            {skill.name}
            <button 
              type="button" 
              onClick={(e) => { e.stopPropagation(); toggleSkill(skill.name); }}
              className="hover:opacity-70"
            >
              <span className="material-symbols-outlined text-[10px] leading-none">close</span>
            </button>
          </span>
        ))}
        {missingSelectedSkillRefs.map(ref => (
          <span
            key={ref}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold bg-slate-100 text-slate-500"
          >
            {ref}
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); toggleSkill(ref); }}
              className="hover:opacity-70"
            >
              <span className="material-symbols-outlined text-[10px] leading-none">close</span>
            </button>
          </span>
        ))}
        <input 
          type="text"
          className="flex-1 bg-transparent border-none outline-none text-xs min-w-[120px]"
          placeholder={selectedSkillRefs.length === 0 ? "Search skills..." : ""}
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          onFocus={() => setIsOpen(true)}
        />
      </div>

      {isOpen && (
        <div 
          className="absolute z-50 mt-2 w-full max-h-72 overflow-auto rounded-xl border shadow-xl fade-in slide-in-from-top-2"
          style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
        >
          {isLoading ? (
            <div className="p-4 text-center text-xs text-text-muted">Loading skills...</div>
          ) : availableSkills.length === 0 ? (
            <div className="p-4 text-center text-xs text-text-muted">No matching skills found</div>
          ) : (
            <div className="p-1">
              {groupedSkills.map(([category, skills]) => (
                <div key={category}>
                  {/* Category header */}
                  <div className="px-3 pt-3 pb-1.5 text-[10px] font-bold uppercase tracking-widest text-text-faint border-b border-border/50 mb-1">
                    {CATEGORY_LABELS[category] || category}
                  </div>
                  {skills.map(skill => (
                    <button
                      key={skill.id}
                      type="button"
                      className="w-full text-left p-3 rounded-lg hover:bg-slate-50 transition-colors group"
                      onClick={() => {
                        toggleSkill(skill.name);
                        setSearchTerm('');
                        setIsOpen(false);
                      }}
                    >
                      <div className="flex items-center justify-between mb-0.5">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-bold group-hover:text-primary transition-colors">{skill.name}</span>
                          {skill.trust_level && (
                            <span className={`px-1.5 py-0.5 rounded text-[9px] font-black uppercase ${TRUST_COLORS[skill.trust_level]?.bg || 'bg-slate-100'} ${TRUST_COLORS[skill.trust_level]?.text || 'text-slate-500'}`}>
                              {skill.trust_level}
                            </span>
                          )}
                        </div>
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-100 uppercase">{skill.category}</span>
                      </div>
                      <div className="text-[11px] text-text-muted line-clamp-1">{skill.description}</div>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
