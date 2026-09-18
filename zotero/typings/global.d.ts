declare const _globalThis: {
  [key: string]: any;
  Zotero: _ZoteroTypes.Zotero;
  ztoolkit: ZToolkit;
  addon: typeof addon;
};

declare type ZToolkit = ReturnType<
  typeof import("../src/utils/ztoolkit").createZToolkit
>;

declare const ztoolkit: ZToolkit;

declare const rootURI: string;

declare const addon: import("../src/addon").default;

declare const __env__: "production" | "development";

// Runtime truth: bare setTimeout exists in plugin scope (pdf-translate uses
// it); Zotero.setTimeout is declared in zotero.d.ts but ABSENT in Zotero 9 —
// calling it throws "Zotero.setTimeout is not a function".
declare function setTimeout(func: () => void, ms: number): number;
