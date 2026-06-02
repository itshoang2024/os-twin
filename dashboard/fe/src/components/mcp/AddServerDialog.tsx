import React, { useState } from 'react';
import { useMcpServers } from '@/hooks/use-mcp';

interface AddServerDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

export const AddServerDialog: React.FC<AddServerDialogProps> = ({ isOpen, onClose }) => {
  const { addServer, refresh } = useMcpServers();
  const [type, setType] = useState<'stdio' | 'http'>('stdio');
  const [name, setName] = useState('');
  const [command, setCommand] = useState('');
  const [args, setArgs] = useState('');
  const [httpUrl, setHttpUrl] = useState('');
  const [env, setEnv] = useState('');
  const [headers, setHeaders] = useState('');
  const [storeInVault, setStoreInVault] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const parseKV = (str: string) => {
    const obj: Record<string, string> = {};
    str.split('\n').forEach(line => {
      const parts = line.split('=');
      if (parts.length >= 2) {
        obj[parts[0].trim()] = parts.slice(1).join('=').trim();
      }
    });
    return obj;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      const server: any = { 
        name, 
        type, 
        store_in_vault: storeInVault 
      };
      if (type === 'stdio') {
        server.command = command;
        if (args) server.args = args.split(' ').filter(a => a);
        if (env) server.env = parseKV(env);
      } else {
        server.httpUrl = httpUrl;
        if (headers) server.headers = parseKV(headers);
      }
      await addServer(server);
      onClose();
      refresh();
      setName('');
      setCommand('');
      setArgs('');
      setHttpUrl('');
      setEnv('');
      setHeaders('');
      setStoreInVault(false);
    } catch (e) {
      alert('Failed to add server');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-300">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden border border-slate-200 animate-in zoom-in-95 duration-300">
        <form onSubmit={handleSubmit}>
          <div className="p-6 space-y-6">
            <div className="flex items-center justify-between border-b border-slate-100 pb-4 mb-2">
              <h2 className="text-xl font-bold text-slate-900">Add MCP Server</h2>
              <button
                type="button"
                onClick={onClose}
                className="text-slate-400 hover:text-slate-600 p-1 hover:bg-slate-50 rounded-full transition-colors"
              >
                <span className="material-symbols-outlined text-2xl">close</span>
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Server Type</label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => setType('stdio')}
                    className={`flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all border-2 ${
                      type === 'stdio' 
                      ? 'bg-orange-50 border-orange-500 text-orange-700' 
                      : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'
                    }`}
                  >
                    <span className="material-symbols-outlined text-lg">terminal</span>
                    Stdio
                  </button>
                  <button
                    type="button"
                    onClick={() => setType('http')}
                    className={`flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all border-2 ${
                      type === 'http' 
                      ? 'bg-purple-50 border-purple-500 text-purple-700' 
                      : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'
                    }`}
                  >
                    <span className="material-symbols-outlined text-lg">language</span>
                    HTTP
                  </button>
                </div>
              </div>

              <div className="space-y-4 animate-in slide-in-from-bottom-2 duration-300">
                <div>
                  <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Server Name</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. google-search"
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </div>

                {type === 'stdio' ? (
                  <>
                    <div>
                      <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Command</label>
                      <input
                        type="text"
                        required
                        placeholder="e.g. npx -y @modelcontextprotocol/server-everything"
                        className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-mono"
                        value={command}
                        onChange={(e) => setCommand(e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Arguments (optional)</label>
                      <input
                        type="text"
                        placeholder="e.g. --debug --port 8080"
                        className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-mono"
                        value={args}
                        onChange={(e) => setArgs(e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">Environment Variables (KEY=VALUE per line)</label>
                      <textarea
                        placeholder="API_KEY=sk-...&#10;DEBUG=true"
                        rows={3}
                        className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-mono resize-none"
                        value={env}
                        onChange={(e) => setEnv(e.target.value)}
                      />
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">HTTP URL</label>
                      <input
                        type="url"
                        required
                        placeholder="https://mcp.example.com/api"
                        className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-mono"
                        value={httpUrl}
                        onChange={(e) => setHttpUrl(e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5">HTTP Headers (KEY=VALUE per line)</label>
                      <textarea
                        placeholder="Authorization=Bearer ...&#10;X-Custom-Header=value"
                        rows={3}
                        className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all font-mono resize-none"
                        value={headers}
                        onChange={(e) => setHeaders(e.target.value)}
                      />
                    </div>
                  </>
                )}

                <div className="flex items-center gap-3 p-3 bg-blue-50 rounded-xl border border-blue-100">
                  <div className="flex-1">
                    <h4 className="text-xs font-bold text-blue-900 mb-0.5">Store in Vault</h4>
                    <p className="text-[10px] text-blue-700 leading-tight">Securely store environment variables and headers in the macOS Keychain/Vault instead of the config file.</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setStoreInVault(!storeInVault)}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
                      storeInVault ? 'bg-blue-600' : 'bg-slate-200'
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        storeInVault ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="p-6 bg-slate-50 flex items-center justify-end gap-3 border-t border-slate-200">
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 text-sm font-semibold text-slate-600 hover:text-slate-800 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-bold rounded-xl shadow-lg shadow-blue-500/20 disabled:opacity-50 transition-all transform active:scale-95"
            >
              {isSubmitting ? 'Adding...' : 'Add Server'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
