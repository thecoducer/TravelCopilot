import type { Itinerary } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

const miniHeading = "mb-2 text-[0.8rem] font-bold uppercase tracking-wide text-faint";
const disclaimerClass = "text-xs leading-relaxed text-faint";

function Checklist({ items }: { items: string[] }) {
  return (
    <ul className="flex list-disc flex-col gap-1 pl-4 text-[0.88rem] text-fg">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export function VisaDetails({ itinerary }: { itinerary: Itinerary }) {
  const visa = itinerary.visa_section;
  if (!visa) return null;
  const centre = visa.application_centre ?? visa.nearest_embassy;
  const lastVerified = formatDateTime(visa.last_verified_at);

  return (
    <section className="flex flex-col gap-6 pb-8 pt-4">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <span className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-faint">
            Entry requirements
          </span>
          <h3 className="mt-1 font-display text-[1.7rem] font-semibold tracking-tight text-fg sm:text-[1.9rem]">
            Visa checklist
          </h3>
        </div>
        <span className="text-sm text-muted">{visa.visa_required ? "Visa required" : "No visa"}</span>
      </header>

      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm text-muted">
          {visa.visa_type ? <span>Type: {visa.visa_type}</span> : null}
          {visa.processing_timeline ? <span>Processing: {visa.processing_timeline}</span> : null}
          {visa.fees ? <span>Fees: {visa.fees}</span> : null}
        </div>

        {visa.documents_required && visa.documents_required.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Documents required</h5>
            <Checklist items={visa.documents_required} />
          </div>
        ) : null}

        {visa.application_process && visa.application_process.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Application steps</h5>
            <ol className="flex list-decimal flex-col gap-2 pl-4 text-[0.88rem] text-fg">
              {visa.application_process.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </div>
        ) : null}

        {visa.dos_and_donts && visa.dos_and_donts.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Do&apos;s and don&apos;ts</h5>
            <Checklist items={visa.dos_and_donts} />
          </div>
        ) : null}

        {centre ? (
          <div>
            <h5 className={miniHeading}>Where to apply</h5>
            <p className="text-[0.88rem] text-fg">
              {centre.name}
              {centre.address ? `, ${centre.address}` : ""}
            </p>
            {centre.booking_url ? (
              <a className="text-xs font-semibold text-chat-blue hover:text-chat-blue-hover hover:underline" href={centre.booking_url} target="_blank" rel="noreferrer">
                Book an appointment
              </a>
            ) : null}
          </div>
        ) : null}

        {visa.apply_online_url ? (
          <a className="text-xs font-semibold text-chat-blue hover:text-chat-blue-hover hover:underline" href={visa.apply_online_url} target="_blank" rel="noreferrer">
            Apply online
          </a>
        ) : null}

        {visa.sources && visa.sources.length > 0 ? (
          <div>
            <h5 className={miniHeading}>Sources</h5>
            <ul className="list-disc pl-4 text-sm">
              {visa.sources.map((source) => (
                <li key={source.url}>
                  <a className="text-chat-blue hover:text-chat-blue-hover hover:underline" href={source.url} target="_blank" rel="noreferrer">
                    {source.title}
                  </a>
                  {source.published_or_fetched_date ? ` — ${source.published_or_fetched_date}` : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {lastVerified ? <small className={disclaimerClass}>Last verified: {lastVerified}</small> : null}
        <small className={disclaimerClass}>{visa.disclaimer}</small>
      </div>
    </section>
  );
}