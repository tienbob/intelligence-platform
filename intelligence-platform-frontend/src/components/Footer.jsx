export default function Footer() {
  return (
    <footer className="w-full py-4 px-container-margin flex flex-col md:flex-row justify-between items-center bg-surface-dim border-t border-outline-variant z-30">
      <p className="text-xs text-on-surface-variant data-font">
        &copy; {new Date().getFullYear()} Market Intelligence. SEC Registered.
      </p>
      <div className="flex gap-4 mt-2 md:mt-0">
        <a
          className="text-xs text-on-surface-variant hover:text-on-surface transition-colors duration-150 data-font"
          href="#"
        >
          Terms of Service
        </a>
        <a
          className="text-xs text-on-surface-variant hover:text-on-surface transition-colors duration-150 data-font"
          href="#"
        >
          Privacy Policy
        </a>
        <a
          className="text-xs text-on-surface-variant hover:text-on-surface transition-colors duration-150 data-font"
          href="#"
        >
          Regulatory Disclosures
        </a>
      </div>
    </footer>
  );
}