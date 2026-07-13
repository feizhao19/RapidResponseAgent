import type { Components } from "react-markdown";

export const reportMarkdownComponents: Components = {
  table: ({ children, ...props }) => (
    <div className="report-table-wrap">
      <table {...props}>{children}</table>
    </div>
  ),
  a: ({ href, children, ...props }) => (
    <a href={href} target="_blank" rel="noreferrer" {...props}>
      {children}
    </a>
  ),
};
