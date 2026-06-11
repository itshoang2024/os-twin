'use client';

import React, { useState, useMemo, useEffect } from 'react';
import { Skill, SkillCategory } from '@/types';
import { useSkills } from '@/hooks/use-skills';
import { apiPatch } from '@/lib/api-client';
import { SkillCard } from './SkillCard';
import { SkillDetailModal } from './SkillDetailModal';
import { ClawhubMarketplace } from './ClawhubMarketplace';

const categoryColors: Record<SkillCategory, string> = {
  implementation: 'var(--color-primary)',
  review: 'var(--color-purple)',
  testing: 'var(--color-success)',
  writing: 'var(--color-amber)',
  analysis: 'var(--color-cyan)',
  compliance: 'var(--color-pink)',
  triage: 'var(--color-danger)',
};

const PAGE_SIZE = 50;

type SortOption = 'name' | 'most-used' | 'recently-updated' | 'category';
type ActiveTab = 'local' | 'clawhub';

interface SkillLibraryProps {
  onEdit?: (skill: Skill) => void;
}

export const SkillLibrary: React.FC<SkillLibraryProps> = ({ onEdit }) => {
  const [activeTab, setActiveTab] = useState<ActiveTab>('local');
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selectedCategories, setSelectedCategories] = useState<SkillCategory[]>([]);
  const [sortOption, setSortOption] = useState<SortOption>('name');
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [togglingSkillName, setTogglingSkillName] = useState<string | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);
  
  const { skills, isLoading, isError, syncWithDisk, refresh } = useSkills(
    selectedCategories.length === 1 ? selectedCategories[0] : undefined,
    undefined,
    debouncedSearch || undefined,
    true // includeDisabled
  );

  const handleToggleSkill = async (skill: Skill) => {
    setToggleError(null);
    setTogglingSkillName(skill.name);
    try {
      const updatedSkill = await apiPatch<Skill>(`/skills/${encodeURIComponent(skill.name)}/toggle`, {});
      await refresh(
        (currentSkills?: Skill[]) =>
          currentSkills?.map((currentSkill) =>
            currentSkill.name === updatedSkill.name
              ? { ...currentSkill, ...updatedSkill }
              : currentSkill
          ),
        { revalidate: true } // revalidate after optimistic update to stay in sync
      );
      setSelectedSkill(current => current?.name === updatedSkill.name ? updatedSkill : current);
    } catch (e) {
      console.error('Failed to toggle skill:', e);
      setToggleError(`Failed to ${skill.enabled === false ? 'enable' : 'disable'} ${skill.name}.`);
    } finally {
      setTogglingSkillName(null);
    }
  };
  
  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchTerm);
    }, 200);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  const toggleCategory = (category: SkillCategory) => {
    setSelectedCategories(prev => 
      prev.includes(category) 
        ? prev.filter(c => c !== category) 
        : [...prev, category]
    );
  };

  const filteredSkills = useMemo(() => {
    if (!skills) return [];

    return skills
      .filter(skill => {
        const matchesSearch = 
          skill.name.toLowerCase().includes(debouncedSearch.toLowerCase()) ||
          skill.description.toLowerCase().includes(debouncedSearch.toLowerCase());
        
        const matchesCategory = 
          selectedCategories.length === 0 || 
          selectedCategories.includes(skill.category);
        
        return matchesSearch && matchesCategory;
      })
      .sort((a, b) => {
        if (debouncedSearch && a.score !== undefined && b.score !== undefined) {
           return b.score - a.score;
        }
        switch (sortOption) {
          case 'most-used':
            return b.usage_count - a.usage_count;
          case 'recently-updated':
            return (b.updated_at || '').localeCompare(a.updated_at || '');
          case 'category':
            return a.category.localeCompare(b.category);
          case 'name':
          default:
            return a.name.localeCompare(b.name);
        }
      });
  }, [skills, debouncedSearch, selectedCategories, sortOption]);

  useEffect(() => {
    setCurrentPage(1);
  }, [debouncedSearch, selectedCategories, sortOption]);

  const totalPages = Math.max(1, Math.ceil(filteredSkills.length / PAGE_SIZE));
  const paginatedSkills = filteredSkills.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  );

  const getPageNumbers = () => {
    const pages: (number | 'ellipsis')[] = [];
    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
      pages.push(1);
      if (currentPage > 3) pages.push('ellipsis');
      for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i++) {
        pages.push(i);
      }
      if (currentPage < totalPages - 2) pages.push('ellipsis');
      pages.push(totalPages);
    }
    return pages;
  };

  if (isError && activeTab === 'local') return <div className="p-8" style={{ color: 'var(--color-danger)' }}>Failed to load skills</div>;

  return (
    <div className="space-y-6">
      {/* Tabs */}
      <div className="flex items-center gap-1 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <button
          onClick={() => setActiveTab('local')}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold border-b-2 transition-colors`}
          style={{
            borderBottomColor: activeTab === 'local' ? 'var(--color-primary)' : 'transparent',
            color: activeTab === 'local' ? 'var(--color-primary)' : 'var(--color-text-muted)',
          }}
        >
          <span className="material-symbols-outlined text-sm">folder</span>
          Local Skills
        </button>
        <button
          onClick={() => setActiveTab('clawhub')}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold border-b-2 transition-colors`}
          style={{
            borderBottomColor: activeTab === 'clawhub' ? 'var(--color-primary)' : 'transparent',
            color: activeTab === 'clawhub' ? 'var(--color-primary)' : 'var(--color-text-muted)',
          }}
        >
          <span className="material-symbols-outlined text-sm">store</span>
          ClawHub Marketplace
        </button>
      </div>

      {/* ClawHub tab */}
      {activeTab === 'clawhub' && (
        <ClawhubMarketplace onInstalled={() => syncWithDisk()} />
      )}

      {/* Local skills tab */}
      {activeTab === 'local' && <>
      {/* Search + Filters */}
      <div className="flex flex-col md:flex-row md:items-center gap-4">
        <div
          className="flex items-center gap-2 px-3 py-2 rounded-lg flex-1 max-w-sm"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <span className="material-symbols-outlined text-base" style={{ color: 'var(--color-text-faint)' }}>search</span>
          <input
            type="text"
            placeholder="Search skills..."
            className="bg-transparent border-none outline-none text-xs w-full"
            style={{ color: 'var(--color-text-main)' }}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <div className="flex items-center gap-1.5 flex-wrap">
          {Object.entries(categoryColors).map(([cat, color]) => {
            const isSelected = selectedCategories.includes(cat as SkillCategory);
            return (
              <button
                key={cat}
                onClick={() => toggleCategory(cat as SkillCategory)}
                className={`flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] font-medium capitalize transition-all border ${
                  isSelected 
                    ? 'border-transparent text-white' 
                    : 'text-text-muted'
                }`}
                style={{ 
                  background: isSelected ? color : 'transparent',
                  borderColor: isSelected ? 'transparent' : 'var(--color-border)'
                }}
                onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = 'var(--color-surface-hover)'; }}
                onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.background = 'transparent'; }}
              >
                {!isSelected && <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />}
                {cat}
              </button>
            );
          })}
          {selectedCategories.length > 0 && (
            <button 
              onClick={() => setSelectedCategories([])}
              className="px-2 py-1 text-[10px] hover:underline"
              style={{ color: 'var(--color-primary)' }}
            >
              Clear
            </button>
          )}
        </div>

        <div className="flex items-center gap-2 md:ml-auto">
          <select 
            className="bg-transparent text-[11px] font-medium border-border rounded px-2 py-1 outline-none"
            style={{ color: 'var(--color-text-muted)', border: '1px solid var(--color-border)' }}
            value={sortOption}
            onChange={(e) => setSortOption(e.target.value as SortOption)}
          >
            <option value="name">Name A-Z</option>
            <option value="most-used">Most Used</option>
            <option value="recently-updated">Recently Updated</option>
            <option value="category">Category</option>
          </select>
          <div className="h-4 w-[1px] bg-border mx-1" />
          <span className="text-[11px] font-medium whitespace-nowrap" style={{ color: 'var(--color-text-faint)' }}>
            {filteredSkills.length} / {skills?.length || 0} skills
          </span>
        </div>
      </div>

      {/* Grid */}
      {toggleError && (
        <div className="rounded-xl border px-4 py-3 text-sm"
          style={{ borderColor: 'var(--color-danger-light)', background: 'var(--color-danger-light)', color: 'var(--color-danger-text)' }}
        >
          {toggleError}
        </div>
      )}
      {isLoading ? (
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-32 rounded-xl animate-pulse" style={{ background: 'var(--color-surface-hover)' }} />
          ))}
        </div>
      ) : paginatedSkills.length > 0 ? (
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
          {paginatedSkills.map((skill) => (
            <SkillCard
              key={skill.name}
              skill={skill}
              onClick={setSelectedSkill}
              onToggle={handleToggleSkill}
              isToggling={togglingSkillName === skill.name}
            />
          ))}
        </div>
      ) : (
        <div className="p-12 text-center border border-dashed border-border rounded-xl">
          <span className="material-symbols-outlined text-4xl mb-2" style={{ color: 'var(--color-text-faint)' }}>
            sentiment_dissatisfied
          </span>
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No skills found matching your filters</p>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-1 pt-2">
          <button
            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
            disabled={currentPage === 1}
            className="flex items-center justify-center w-8 h-8 rounded-md text-xs transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ color: 'var(--color-text-muted)', border: '1px solid var(--color-border)', background: 'transparent' }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'var(--color-surface-hover)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
          >
            <span className="material-symbols-outlined text-sm">chevron_left</span>
          </button>
          {getPageNumbers().map((page, i) =>
            page === 'ellipsis' ? (
              <span key={`e-${i}`} className="w-8 h-8 flex items-center justify-center text-xs" style={{ color: 'var(--color-text-faint)' }}>
                ...
              </span>
            ) : (
              <button
                key={page}
                onClick={() => setCurrentPage(page)}
                className={`w-8 h-8 rounded-md text-xs font-medium transition-colors`}
                style={{
                  background: currentPage === page ? 'var(--color-primary)' : 'transparent',
                  color: currentPage === page ? 'var(--color-surface)' : 'var(--color-text-muted)',
                  border: currentPage === page ? 'none' : '1px solid var(--color-border)',
                }}
              >
                {page}
              </button>
            )
          )}
          <button
            onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
            disabled={currentPage === totalPages}
            className="flex items-center justify-center w-8 h-8 rounded-md text-xs transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            style={{ color: 'var(--color-text-muted)', border: '1px solid var(--color-border)', background: 'transparent' }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'var(--color-surface-hover)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
          >
            <span className="material-symbols-outlined text-sm">chevron_right</span>
          </button>
          <span className="ml-3 text-[11px]" style={{ color: 'var(--color-text-faint)' }}>
            {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, filteredSkills.length)} of {filteredSkills.length}
          </span>
        </div>
      )}

      </>}

      {/* Modal */}
      <SkillDetailModal
        isOpen={!!selectedSkill}
        skill={selectedSkill}
        onClose={() => setSelectedSkill(null)}
        onEdit={onEdit}
        onToggle={handleToggleSkill}
        isToggling={selectedSkill ? togglingSkillName === selectedSkill.name : false}
      />
    </div>
  );
};
