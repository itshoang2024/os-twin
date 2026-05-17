import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

import { KnowledgePanel } from '../components/settings/KnowledgePanel';
import type { KnowledgeSettings, ModelInfo } from '../types/settings';

const mockModels: ModelInfo[] = [
  { id: 'anthropic/claude-haiku-4-5', label: 'Claude Haiku 4.5', provider_id: 'anthropic' },
  { id: 'openai/gpt-5',               label: 'GPT-5',            provider_id: 'openai' },
  { id: 'openai/text-embedding-3-small', label: 'OpenAI Embedding', provider_id: 'openai' },
];

const defaults: KnowledgeSettings = {
  knowledge_llm_backend: '',
  knowledge_llm_model: '',
  knowledge_embedding_backend: '',
  knowledge_embedding_model: '',
  knowledge_embedding_dimension: 768,
};

function openLlmDropdown() {
  const trigger = screen.getAllByRole('button').find(
    (b) =>
      b.textContent?.includes('— Select from providers —') ||
      b.textContent?.includes('Claude Haiku') ||
      b.textContent?.includes('GPT-5')
  );
  if (!trigger) throw new Error('ModelSelect trigger button not found');
  fireEvent.click(trigger);
  return trigger;
}

describe('KnowledgePanel', () => {
  it('renders LLM, embedding, and dimension sections', () => {
    const onUpdate = vi.fn();
    render(<KnowledgePanel knowledge={defaults} onUpdate={onUpdate} allModels={mockModels} />);

    expect(screen.getByText(/Knowledge Models/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Processing Model/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Model$/i).length).toBeGreaterThan(0); // The "Model" labels
    expect(screen.getAllByText(/Embedding Dimension/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/HuggingFace \(Local\)/i)).not.toBeInTheDocument();
  });

  it('shows the selected model label in the trigger when an LLM is set', () => {
    const onUpdate = vi.fn();
    render(
      <KnowledgePanel
        knowledge={{ ...defaults, knowledge_llm_backend: 'openai-compatible', knowledge_llm_model: 'anthropic/claude-haiku-4-5' }}
        onUpdate={onUpdate}
        allModels={mockModels}
      />,
    );
    expect(screen.getByText(/Claude Haiku 4\.5/i)).toBeInTheDocument();
  });

  it('filters out embedding models from the LLM picker dropdown', () => {
    const onUpdate = vi.fn();
    render(<KnowledgePanel knowledge={{ ...defaults, knowledge_llm_backend: 'openai-compatible' }} onUpdate={onUpdate} allModels={mockModels} />);

    openLlmDropdown();

    expect(screen.getByText(/Claude Haiku 4\.5/)).toBeInTheDocument();
    expect(screen.getByText(/GPT-5/)).toBeInTheDocument();
    expect(screen.queryByText(/OpenAI Embedding/)).not.toBeInTheDocument();
  });

  it('shows the placeholder when no LLM is set', () => {
    const onUpdate = vi.fn();
    render(<KnowledgePanel knowledge={{ ...defaults, knowledge_llm_backend: 'openai-compatible' }} onUpdate={onUpdate} allModels={mockModels} />);
    expect(screen.getAllByText(/— Select from providers —/i).length).toBeGreaterThanOrEqual(1);
  });

  it('calls onUpdate when a model is selected from the LLM picker', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(<KnowledgePanel knowledge={{ ...defaults, knowledge_llm_backend: 'openai-compatible' }} onUpdate={onUpdate} allModels={mockModels} />);

    openLlmDropdown();

    const option = screen.getByRole('button', { name: /GPT-5/ });
    fireEvent.click(option);

    expect(screen.getByText('Save Knowledge Settings')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Save Knowledge Settings'));

    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ knowledge_llm_model: 'openai/gpt-5' }));
    });
  });

  it('calls onUpdate with model + dimension when a suggested embedding is clicked', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(<KnowledgePanel knowledge={{ ...defaults, knowledge_embedding_backend: 'ollama' }} onUpdate={onUpdate} allModels={mockModels} />);

    // In ollama backend, there's a suggested model button
    const button = screen.getByRole('button', { name: /Harrier 0\.6B/i });
    fireEvent.click(button);

    expect(screen.getByText('Save Knowledge Settings')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Save Knowledge Settings'));

    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({
        knowledge_embedding_model: 'leoipulsar/harrier-0.6b',
        knowledge_embedding_dimension: 768,
      }));
    });
  });

  it('calls onUpdate when the embedding input is changed and blurred with a custom id', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(<KnowledgePanel knowledge={defaults} onUpdate={onUpdate} allModels={mockModels} />);

    // Switch backend to ollama to see the input. The second one is for embeddings.
    const backendBtns = screen.getAllByRole('button', { name: /Ollama \(Local\)/i });
    fireEvent.click(backendBtns[1]);

    const input = screen.getByPlaceholderText(/e\.g\. leoipulsar\/harrier-0\.6b/i);
    fireEvent.change(input, { target: { value: 'custom/model-id' } });
    fireEvent.blur(input);

    expect(screen.getByText('Save Knowledge Settings')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Save Knowledge Settings'));

    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({
        knowledge_embedding_model: 'custom/model-id',
        knowledge_embedding_dimension: 768,
      }));
    });
  });

  it('shows the read-only embedding dimension', () => {
    const onUpdate = vi.fn();
    render(
      <KnowledgePanel
        knowledge={{ ...defaults, knowledge_embedding_dimension: 768 }}
        onUpdate={onUpdate}
        allModels={mockModels}
      />,
    );

    const elements = screen.getAllByText('768');
    expect(elements.length).toBeGreaterThan(0);
    expect(screen.getByText(/dimensions \(from env\)/i)).toBeInTheDocument();
  });

  it('hides provider dropdown when no models are configured', () => {
    const onUpdate = vi.fn();
    render(<KnowledgePanel knowledge={{...defaults, knowledge_llm_backend: 'openai-compatible'}} onUpdate={onUpdate} allModels={[]} />);
    // When allModels is empty, the ModelSelect is not rendered, so "— Select from providers —" will not exist.
    expect(screen.queryByText(/— Select from providers —/i)).not.toBeInTheDocument();
  });
});
