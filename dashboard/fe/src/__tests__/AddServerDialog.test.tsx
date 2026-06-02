import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AddServerDialog, normalizeMcpHttpUrl } from '@/components/mcp/AddServerDialog';
import { useMcpServers } from '@/hooks/use-mcp';

vi.mock('@/hooks/use-mcp', () => ({
  useMcpServers: vi.fn(),
}));

describe('AddServerDialog', () => {
  const addServer = vi.fn();
  const refresh = vi.fn();
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    addServer.mockResolvedValue({});
    (useMcpServers as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      addServer,
      refresh,
    });
  });

  it('normalizes bare HTTP hosts before adding a server', async () => {
    render(<AddServerDialog isOpen={true} onClose={onClose} />);

    fireEvent.click(screen.getByRole('button', { name: /HTTP/ }));
    fireEvent.change(screen.getByLabelText('Server Name'), {
      target: { value: 'remote-server' },
    });

    const urlInput = screen.getByLabelText('HTTP URL');
    expect(urlInput).toHaveAttribute('type', 'text');
    fireEvent.change(urlInput, {
      target: { value: 'example.com/mcp' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Add Server' }));

    await waitFor(() => {
      expect(addServer).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'remote-server',
          type: 'http',
          httpUrl: 'https://example.com/mcp',
        })
      );
    });
  });

  it('keeps explicit HTTP schemes unchanged', () => {
    expect(normalizeMcpHttpUrl('http://localhost:8080/sse')).toBe('http://localhost:8080/sse');
    expect(normalizeMcpHttpUrl(' https://example.com/mcp ')).toBe('https://example.com/mcp');
  });

  it('uses HTTP for bare localhost URLs', () => {
    expect(normalizeMcpHttpUrl('localhost:8080/sse')).toBe('http://localhost:8080/sse');
    expect(normalizeMcpHttpUrl('127.0.0.1:8080/mcp')).toBe('http://127.0.0.1:8080/mcp');
  });
});
