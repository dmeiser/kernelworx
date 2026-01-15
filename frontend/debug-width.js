/**
 * Debug script to measure page width and find overflow issues
 * Run with: node debug-width.js
 */

import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({
    viewport: { width: 430, height: 932 },
    deviceScaleFactor: 3,
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  // Go to the local dev server
  console.log('Navigating to local dev...');
  await page.goto('https://local.dev.appworx.app:5173');
  
  // Wait for page to load
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);
  
  console.log('Current URL:', page.url());
  console.log('\nPlease log in manually in the browser window...');
  console.log('Then navigate to a seller profile Reports page');
  console.log('Press Enter when ready to measure widths...\n');
  
  // Wait for user input
  await new Promise((resolve) => {
    process.stdin.once('data', resolve);
  });
  
  console.log('Page loaded, measuring widths...\n');

  // Get detailed info about the main Box and Container
  const layoutInfo = await page.evaluate(() => {
    const main = document.querySelector('main.MuiBox-root');
    const container = document.querySelector('main.MuiBox-root > div.MuiContainer-root, main.MuiBox-root > div[class*="Container"]');
    
    const getInfo = (el, name) => {
      if (!el) return null;
      const computed = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return {
        name,
        tagName: el.tagName,
        className: el.className,
        rect: { width: rect.width, left: rect.left, right: rect.right },
        computed: {
          width: computed.width,
          maxWidth: computed.maxWidth,
          minWidth: computed.minWidth,
          flexGrow: computed.flexGrow,
          boxSizing: computed.boxSizing,
        },
        parentWidth: el.parentElement?.getBoundingClientRect().width,
      };
    };
    
    return {
      main: getInfo(main, 'Main Box'),
      container: getInfo(container, 'Container'),
    };
  });

  console.log('=== MAIN BOX DETAILS ===');
  if (layoutInfo.main) {
    console.log(`Class: ${layoutInfo.main.className}`);
    console.log(`Width: ${layoutInfo.main.rect.width}px`);
    console.log(`Computed width: ${layoutInfo.main.computed.width}`);
    console.log(`Max-width: ${layoutInfo.main.computed.maxWidth}`);
    console.log(`Min-width: ${layoutInfo.main.computed.minWidth}`);
    console.log(`Flex-grow: ${layoutInfo.main.computed.flexGrow}`);
    console.log(`Parent width: ${layoutInfo.main.parentWidth}px\n`);
  }

  console.log('=== CONTAINER DETAILS ===');
  if (layoutInfo.container) {
    console.log(`Class: ${layoutInfo.container.className}`);
    console.log(`Width: ${layoutInfo.container.rect.width}px`);
    console.log(`Computed width: ${layoutInfo.container.computed.width}`);
    console.log(`Max-width: ${layoutInfo.container.computed.maxWidth}`);
    console.log(`Min-width: ${layoutInfo.container.computed.minWidth}`);
    console.log(`Parent width: ${layoutInfo.container.parentWidth}px\n`);
  }

  // Function to measure all elements and find those wider than viewport
  const measurements = await page.evaluate(() => {
    const results = [];
    const viewportWidth = 430;
    
    // Check all elements
    const allElements = document.querySelectorAll('*');
    // eslint-disable-next-line complexity
    allElements.forEach((el) => {
      const rect = el.getBoundingClientRect();
      const computedStyle = window.getComputedStyle(el);
      
      // Check if element extends beyond viewport
      if (rect.width > viewportWidth || rect.right > viewportWidth) {
        const tagName = el.tagName.toLowerCase();
        const className = typeof el.className === 'string' ? el.className : '';
        const id = el.id || '';
        
        results.push({
          element: `${tagName}${id ? '#' + id : ''}${className ? '.' + className.split(' ')[0] : ''}`,
          width: Math.round(rect.width),
          right: Math.round(rect.right),
          left: Math.round(rect.left),
          minWidth: computedStyle.minWidth,
          maxWidth: computedStyle.maxWidth,
          paddingLeft: computedStyle.paddingLeft,
          paddingRight: computedStyle.paddingRight,
          marginLeft: computedStyle.marginLeft,
          marginRight: computedStyle.marginRight,
          overflow: computedStyle.overflow,
          overflowX: computedStyle.overflowX,
        });
      }
    });
    
    // Sort by width (largest first)
    results.sort((a, b) => b.width - a.width);
    
    return {
      viewportWidth,
      bodyWidth: document.body.getBoundingClientRect().width,
      documentWidth: document.documentElement.getBoundingClientRect().width,
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      overflowingElements: results.slice(0, 20), // Top 20
    };
  });

  console.log('=== WIDTH ANALYSIS ===');
  console.log(`Viewport width: ${measurements.viewportWidth}px`);
  console.log(`Body width: ${measurements.bodyWidth}px`);
  console.log(`Document width: ${measurements.documentWidth}px`);
  console.log(`Scroll width: ${measurements.scrollWidth}px`);
  console.log(`Client width: ${measurements.clientWidth}px`);
  console.log(`\nOverflow detected: ${measurements.scrollWidth > measurements.viewportWidth ? 'YES' : 'NO'}`);
  console.log(`Overflow amount: ${measurements.scrollWidth - measurements.viewportWidth}px\n`);

  console.log('=== TOP OVERFLOWING ELEMENTS ===');
  measurements.overflowingElements.forEach((el, i) => {
    console.log(`\n${i + 1}. ${el.element}`);
    console.log(`   Width: ${el.width}px (extends ${el.width - measurements.viewportWidth}px beyond viewport)`);
    console.log(`   Position: left=${el.left}px, right=${el.right}px`);
    console.log(`   Min-width: ${el.minWidth}, Max-width: ${el.maxWidth}`);
    console.log(`   Padding: ${el.paddingLeft} | ${el.paddingRight}`);
    console.log(`   Margin: ${el.marginLeft} | ${el.marginRight}`);
    console.log(`   Overflow: ${el.overflow}, Overflow-X: ${el.overflowX}`);
  });

  console.log('\n\nPress Ctrl+C to close the browser...');
  
  // Keep browser open for inspection
  await new Promise(() => {});
})();
