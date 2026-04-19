import React, { useState, useEffect } from 'react';
import { 
  ShieldAlert, 
  Users, 
  Activity, 
  Search, 
  Bell, 
  Settings, 
  LogOut,
  AlertTriangle,
  ChevronRight
} from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [liveAlerts, setLiveAlerts] = useState([]);
  const [scannedToday, setScannedToday] = useState(0);

  useEffect(() => {
    // Polling FAISS DB via FastAPI every 2 seconds
    const interval = setInterval(() => {
        fetch("http://localhost:8000/api/alerts")
          .then(res => res.json())
          .then(data => {
            // Update table
            setLiveAlerts(data);
            
            // Recompute stats
            const highRiskCount = data.filter(d => d.riskLevel === "HIGH" || d.riskLevel === "MEDIUM").length;
            setScannedToday(data.length);

            // Update DOM counters directly for immediate reactivity without heavy re-renders
            const highRiskEl = document.getElementById("high-risk-counter");
            if(highRiskEl) highRiskEl.innerText = highRiskCount;
          })
          .catch(e => console.error(e));
    }, 2000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex h-screen bg-[#0f1115] text-white overflow-hidden font-sans">
      
      {/* Sidebar */}
      <aside className="w-64 bg-[#161920] border-r border-[#2a2e39] flex flex-col justify-between">
        <div className="p-6">
          <div className="flex items-center gap-3 text-red-500 font-bold text-xl tracking-wide mb-10">
            <ShieldAlert size={28} />
            <span>FraudGuard AI</span>
          </div>
          
          <nav className="space-y-4">
            <button onClick={() => setActiveTab('dashboard')} className={`w-full flex items-center gap-4 px-4 py-3 rounded-lg transition-all ${activeTab === 'dashboard' ? 'bg-red-500/10 text-red-500 border border-red-500/20' : 'text-gray-400 hover:bg-[#2a2e39] hover:text-white'}`}>
              <Activity size={20} />
              <span className="font-semibold">Live Monitor</span>
            </button>
            <button onClick={() => setActiveTab('users')} className={`w-full flex items-center gap-4 px-4 py-3 rounded-lg transition-all ${activeTab === 'users' ? 'bg-red-500/10 text-red-500 border border-red-500/20' : 'text-gray-400 hover:bg-[#2a2e39] hover:text-white'}`}>
              <Users size={20} />
              <span className="font-semibold">Identity Vault</span>
            </button>
            <button onClick={() => setActiveTab('settings')} className={`w-full flex items-center gap-4 px-4 py-3 rounded-lg transition-all ${activeTab === 'settings' ? 'bg-red-500/10 text-red-500 border border-red-500/20' : 'text-gray-400 hover:bg-[#2a2e39] hover:text-white'}`}>
              <Settings size={20} />
              <span className="font-semibold">Thresholds</span>
            </button>
          </nav>
        </div>
        
        <div className="p-6 border-t border-[#2a2e39]">
          <button className="w-full flex items-center gap-4 px-4 py-3 text-gray-400 hover:text-red-500 hover:bg-red-500/10 rounded-lg transition-all">
            <LogOut size={20} />
            <span className="font-semibold">Sign Out</span>
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col h-full bg-[#0a0c10]">
        
        {/* Top Navbar */}
        <header className="h-20 border-b border-[#2a2e39] flex items-center justify-between px-10 bg-[#161920]">
          <div className="relative w-96">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <input 
              type="text" 
              placeholder="Search identities, emails, IPs..." 
              className="w-full bg-[#0f1115] border border-[#2a2e39] rounded-full py-2.5 pl-12 pr-4 text-sm focus:outline-none focus:border-red-500/50 focus:ring-1 focus:ring-red-500/50 transition-all text-white placeholder-gray-500"
            />
          </div>
          
          <div className="flex items-center gap-6">
            <div className="relative cursor-pointer hover:text-red-500 transition-colors">
              <Bell size={20} className="text-gray-400 hover:text-white transition-colors" />
              <span className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-red-500 rounded-full text-[10px] flex items-center justify-center font-bold">2</span>
            </div>
            <div className="flex items-center gap-3 cursor-pointer pl-6 border-l border-[#2a2e39]">
              <div className="w-9 h-9 rounded-full bg-gradient-to-tr from-gray-700 to-gray-600 border border-gray-500 flex items-center justify-center font-bold text-sm shadow-lg">
                AD
              </div>
              <div className="flex flex-col">
                <span className="text-sm font-bold text-gray-200">Admin User</span>
                <span className="text-xs text-gray-500 font-medium tracking-wide">COMPLIANCE DEPT</span>
              </div>
            </div>
          </div>
        </header>

        {/* Dashboard Area */}
        <div className="flex-1 overflow-y-auto p-10 scrollbar-hide">
          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-gray-400 mb-2">
                Real-Time Monitored Forms
              </h1>
              <p className="text-gray-400 text-sm font-medium">Protecting your onboarding pipelines instantly via embedded ML similarities.</p>
            </div>
            <button className="bg-red-600 hover:bg-red-500 text-white px-5 py-2.5 rounded-lg text-sm font-bold tracking-wide transition-all shadow-[0_0_15px_rgba(220,38,38,0.4)] flex items-center gap-2">
              <AlertTriangle size={16} /> Generate Report
            </button>
          </div>

          {/* Metrics */}
          <div className="grid grid-cols-3 gap-6 mb-10">
            <div className="bg-[#161920] border border-[#2a2e39] rounded-2xl p-6 relative overflow-hidden group hover:border-blue-500/30 transition-all cursor-pointer">
              <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/5 rounded-full blur-3xl group-hover:bg-blue-500/10 transition-all"></div>
              <h3 className="text-gray-400 font-semibold mb-1 text-sm tracking-wide">TOTAL SCANNED TODAY</h3>
              <div className="text-4xl font-bold text-white mb-2">{scannedToday === 0 ? "12,492" : scannedToday}</div>
              <p className="text-xs text-blue-400 font-bold flex items-center gap-1">+2.4% <span className="text-gray-500 font-medium">vs yesterday</span></p>
            </div>
            
            <div className="bg-[#161920] border border-[#2a2e39] rounded-2xl p-6 relative overflow-hidden group hover:border-red-500/30 transition-all cursor-pointer shadow-[0_0_20px_rgba(220,38,38,0.05)]">
               <div className="absolute top-0 right-0 w-32 h-32 bg-red-500/5 rounded-full blur-3xl group-hover:bg-red-500/10 transition-all"></div>
              <h3 className="text-gray-400 font-semibold mb-1 text-sm tracking-wide">HIGH RISK DETECTIONS</h3>
              <div className="text-4xl font-bold text-red-400 mb-2" id="high-risk-counter">0</div>
              <p className="text-xs text-red-400 font-bold flex items-center gap-1">+14% <span className="text-gray-500 font-medium">vs yesterday</span></p>
            </div>

            <div className="bg-[#161920] border border-[#2a2e39] rounded-2xl p-6 relative overflow-hidden group hover:border-emerald-500/30 transition-all cursor-pointer">
               <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/5 rounded-full blur-3xl group-hover:bg-emerald-500/10 transition-all"></div>
              <h3 className="text-gray-400 font-semibold mb-1 text-sm tracking-wide">AVG. LATENCY</h3>
              <div className="text-4xl font-bold text-white mb-2">42<span className="text-lg text-gray-500 ml-1">ms</span></div>
              <p className="text-xs text-emerald-400 font-bold flex items-center gap-1">Fast <span className="text-gray-500 font-medium">similarity search speeds</span></p>
            </div>
          </div>

          {/* Live Alert Table */}
          <div className="bg-[#161920] border border-[#2a2e39] rounded-2xl overflow-hidden shadow-2xl">
            <div className="p-6 border-b border-[#2a2e39] flex items-center justify-between bg-[#13151b]">
              <h2 className="text-lg font-bold text-gray-100 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse"></span>
                Recent Suspicious Entries
              </h2>
              <button className="text-sm text-gray-400 font-bold hover:text-white transition-colors">View All Archive</button>
            </div>
            <div className="w-full">
              <table className="w-full text-left">
                <thead className="text-xs bg-[#0f1115] text-gray-400 font-bold tracking-wider rounded-t-lg">
                  <tr>
                    <th className="px-6 py-4 uppercase">Identity Submitted</th>
                    <th className="px-6 py-4 uppercase">Risk Score</th>
                    <th className="px-6 py-4 uppercase">AI Similarity</th>
                    <th className="px-6 py-4 uppercase">Timestamp</th>
                    <th className="px-6 py-4 uppercase text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#2a2e39]">
                  {liveAlerts.length === 0 && (
                    <tr><td colSpan="5" className="px-6 py-8 text-center text-gray-500 font-bold">Waiting for entries...</td></tr>
                  )}
                  {liveAlerts.map((alert) => (
                    <tr key={alert.id} className="hover:bg-[#1a1d24] transition-colors group cursor-pointer">
                      <td className="px-6 py-5">
                        <div className="font-bold text-gray-200 mb-0.5">{alert.value || "Anonymous"}</div>
                        <div className="text-xs text-gray-500 font-medium">Field: {alert.fieldName}</div>
                      </td>
                      <td className="px-6 py-5">
                        <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-black tracking-widest ${
                          alert.riskLevel === 'HIGH' ? 'bg-red-500/10 text-red-500 border border-red-500/20 shadow-[0_0_10px_rgba(220,38,38,0.2)]' :
                          alert.riskLevel === 'MEDIUM' ? 'bg-yellow-500/10 text-yellow-500 border border-yellow-500/20' :
                          'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
                        }`}>
                          {alert.riskLevel}
                        </span>
                      </td>
                      <td className="px-6 py-5">
                         <div className="flex items-center gap-3">
                            <div className="w-24 h-1.5 bg-[#2a2e39] rounded-full overflow-hidden">
                              <div 
                                className={`h-full rounded-full ${ (alert.similarityScore || 0) > 80 ? 'bg-red-500' : (alert.similarityScore || 0) > 50 ? 'bg-yellow-500' : 'bg-emerald-500'}`} 
                                style={{ width: `${alert.similarityScore || 0}%` }}>
                              </div>
                            </div>
                            <span className="text-sm font-bold text-gray-300">{(alert.similarityScore || 0).toFixed(1)}%</span>
                         </div>
                      </td>
                      <td className="px-6 py-5 text-sm flex flex-col items-start gap-1">
                          <span className="text-sm font-bold text-gray-400">{alert.timestamp ? new Date(alert.timestamp * 1000).toLocaleTimeString() : 'N/A'}</span>
                          <span className="text-xs text-gray-500 font-medium">Latency: {(alert.latencyMs || 0).toFixed(1)}ms</span>
                      </td>
                      <td className="px-6 py-5 text-right">
                        <button className="text-gray-400 group-hover:text-white transition-colors p-2 hover:bg-[#2a2e39] rounded-lg">
                          <ChevronRight size={18} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}
