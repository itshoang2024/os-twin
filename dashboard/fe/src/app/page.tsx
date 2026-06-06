const gardenCards = [
  {
    title: 'Plant',
    icon: '🌱',
    description: 'Tuck a tiny seed into soft soil and watch it wake up.',
    accent: 'bg-emerald-100 text-emerald-900 border-emerald-200',
  },
  {
    title: 'Water',
    icon: '💧',
    description: 'Give thirsty sprouts a gentle drink so they can grow tall.',
    accent: 'bg-sky-100 text-sky-900 border-sky-200',
  },
  {
    title: 'Explore',
    icon: '🦋',
    description: 'Look for butterflies, bugs, and animal friends in the garden.',
    accent: 'bg-amber-100 text-amber-950 border-amber-200',
  },
];

export default function KidsGardenLandingPage() {
  return (
    <main className="min-h-[calc(100vh-theme(spacing.16))] overflow-y-auto bg-gradient-to-b from-lime-50 via-sky-50 to-orange-50 px-4 py-8 text-slate-900 sm:px-6 lg:px-8">
      <section className="mx-auto flex w-full max-w-6xl flex-col items-center rounded-[2rem] border-4 border-white bg-white/80 px-5 py-10 text-center shadow-[0_24px_80px_rgba(34,197,94,0.18)] sm:px-8 lg:px-12">
        <p className="mb-4 rounded-full border-2 border-lime-200 bg-lime-100 px-4 py-2 text-base font-bold text-lime-900">
          A tiny garden adventure
        </p>

        <h1 className="max-w-3xl text-5xl font-black leading-[1.05] tracking-tight text-emerald-900 sm:text-6xl lg:text-7xl">
          Kids Garden
        </h1>

        <p className="mt-6 max-w-2xl text-xl font-semibold leading-8 text-slate-700 sm:text-2xl sm:leading-9">
          Welcome, little gardener! Plant seeds, splash water, and explore a happy garden full of friendly surprises.
        </p>

        <a
          href="#animal-friends"
          className="mt-8 inline-flex min-h-14 items-center justify-center rounded-full bg-emerald-700 px-7 py-4 text-lg font-extrabold text-white shadow-lg shadow-emerald-700/20 outline-none transition-colors hover:bg-emerald-800 focus-visible:ring-4 focus-visible:ring-amber-400 focus-visible:ring-offset-4"
          aria-label="Choose an Animal Friend in the Kids Garden"
        >
          Choose an Animal Friend
        </a>

        <div className="mt-10 grid w-full gap-5 sm:grid-cols-2 lg:grid-cols-3" aria-label="Garden activities">
          {gardenCards.map((card) => (
            <article
              key={card.title}
              className={`rounded-3xl border-2 p-6 text-left shadow-sm ${card.accent}`}
              aria-label={`${card.title} activity`}
            >
              <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-white text-4xl shadow-sm" aria-hidden="true">
                {card.icon}
              </div>
              <h2 className="text-3xl font-black">{card.title}</h2>
              <p className="mt-3 text-lg font-semibold leading-7">{card.description}</p>
            </article>
          ))}
        </div>

        <section
          id="animal-friends"
          className="mt-10 w-full rounded-3xl border-2 border-dashed border-emerald-300 bg-emerald-50 p-6 text-left sm:p-8"
          aria-labelledby="animal-friends-title"
        >
          <h2 id="animal-friends-title" className="text-2xl font-black text-emerald-900 sm:text-3xl">
            Animal friends are coming soon!
          </h2>
          <p className="mt-3 text-lg font-semibold leading-7 text-slate-700">
            Soon you can pick a bunny, turtle, or bird to help you explore the garden.
          </p>
        </section>
      </section>
    </main>
  );
}
