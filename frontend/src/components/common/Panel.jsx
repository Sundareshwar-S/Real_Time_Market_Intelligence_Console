export default function Panel({ title, subtitle, actions, className = "", children }) {
  return (
    <section className={`panel ${className}`.trim()}>
      {(title || subtitle || actions) && (
        <div className="panel-header">
          <div>
            {title ? <h3>{title}</h3> : null}
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          {actions ? <div className="panel-actions">{actions}</div> : null}
        </div>
      )}
      <div>{children}</div>
    </section>
  );
}
