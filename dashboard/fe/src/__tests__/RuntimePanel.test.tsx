import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import '@testing-library/jest-dom';

import { RuntimePanel } from '../components/settings/RuntimePanel';

describe('RuntimePanel', () => {
  const runtime = {
    poll_interval_seconds: 5,
    max_concurrent_rooms: 10,
    max_engineer_retries: 3,
    state_timeout_seconds: 900,
    auto_approve_tools: false,
    dynamic_pipelines: true,
    master_agent_model: '',
  };

  it('updates the canonical poll_interval_seconds field', () => {
    const onUpdate = vi.fn();

    render(
      <RuntimePanel
        runtime={runtime}
        onUpdate={onUpdate}
        allModels={[]}
      />
    );

    const pollSlider = screen.getAllByRole('slider')[0];
    fireEvent.change(pollSlider, { target: { value: '12' } });
    fireEvent.mouseUp(pollSlider);

    expect(onUpdate).toHaveBeenCalledWith({ poll_interval_seconds: 12 });
  });

  it('updates the default state timeout setting', () => {
    const onUpdate = vi.fn();

    render(
      <RuntimePanel
        runtime={runtime}
        onUpdate={onUpdate}
        allModels={[]}
      />
    );

    const timeoutInput = screen.getByLabelText('State Timeout');
    fireEvent.change(timeoutInput, { target: { value: '1800' } });
    fireEvent.blur(timeoutInput);

    expect(onUpdate).toHaveBeenCalledWith({ state_timeout_seconds: 1800 });
  });

  it('updates the default war-room retry setting', () => {
    const onUpdate = vi.fn();

    render(
      <RuntimePanel
        runtime={runtime}
        onUpdate={onUpdate}
        allModels={[]}
      />
    );

    const retryInput = screen.getByLabelText('Max War-Room Retries');
    fireEvent.change(retryInput, { target: { value: '7' } });
    fireEvent.blur(retryInput);

    expect(onUpdate).toHaveBeenCalledWith({ max_engineer_retries: 7 });
  });
});
