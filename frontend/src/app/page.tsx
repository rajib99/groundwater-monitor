export default function Home() {
  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 p-8">
      <div className="max-w-5xl mx-auto">
        <header className="mb-10">
          <h1 className="text-3xl font-bold text-blue-400">Groundwater Monitor</h1>
          <p className="text-gray-400 mt-1">Real-time sensor data and forecasting</p>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
          {[
            { label: "Active Sensors", value: "—" },
            { label: "Latest Reading", value: "—" },
            { label: "Forecast (7d)", value: "—" },
          ].map((stat) => (
            <div key={stat.label} className="bg-gray-900 rounded-xl p-6 border border-gray-800">
              <p className="text-sm text-gray-400">{stat.label}</p>
              <p className="text-2xl font-semibold mt-1">{stat.value}</p>
            </div>
          ))}
        </div>

        <div className="bg-gray-900 rounded-xl p-6 border border-gray-800">
          <h2 className="text-lg font-semibold mb-4">Water Level History</h2>
          <div className="h-48 flex items-center justify-center text-gray-500 text-sm">
            Connect a sensor to start seeing data
          </div>
        </div>
      </div>
    </main>
  );
}
