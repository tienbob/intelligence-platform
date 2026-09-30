import Sidebar from './Sidebar';
import TopNav from './TopNav';
import Footer from './Footer';
import MobileNav from './MobileNav';

export default function Layout({ children }) {
  return (
    <div className="min-h-screen flex flex-col bg-background">
      {/* Skip link: first tab stop on the page, jumps straight to main
          content (audit U08). */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:z-[60] focus:top-2 focus:left-2 focus:bg-surface-container-high focus:text-on-surface focus:px-4 focus:py-2 focus:rounded focus:border focus:border-secondary"
      >
        Skip to main content
      </a>
      <TopNav />
      <Sidebar />
      {/* pb-16 keeps content/footer clear of the MobileNav bottom bar on small screens */}
      <div className="flex-1 flex flex-col md:ml-sidebar-width md:pt-16 pb-16 md:pb-0">
        <main id="main" tabIndex={-1} className="flex-1 overflow-y-auto p-container-margin focus:outline-none">
          {children}
        </main>
        <Footer />
      </div>
      <MobileNav />
    </div>
  );
}
