const fs = require('fs');
const os = require('os');
const path = require('path');
const { Worker, isMainThread, parentPort, workerData } = require('worker_threads');
const PNG = require('pngjs').PNG;
const ImageTracer = require('../public/javascript/imagetracer_v1.2.1.js');

// ---------------------------------------------------------------------------
// Tracing options.
//
// ImageTracer's thresholds are measured in source pixels, so they only mean the same
// thing at the resolution they were tuned for (128px, the model's output size). Glyph
// PNGs now arrive upscaled (see font_processor.prepare_trace_images) so the tracer can
// read anti-aliased edges at sub-pixel accuracy; scaling the thresholds with the input
// keeps the same shape tolerance while gaining that accuracy, instead of exploding the
// point count.
// ---------------------------------------------------------------------------
const BASE_IMAGE_SIZE = 128;

function envNumber(name) {
    const raw = process.env[name];
    if (raw === undefined || raw === '') return undefined;
    const value = Number(raw);
    return Number.isFinite(value) ? value : undefined;
}

function buildTraceOptions(imageSize) {
    const scale = Math.max(1, imageSize / BASE_IMAGE_SIZE);
    const pick = (name, fallback) => {
        const override = envNumber(name);
        return override === undefined ? fallback : override;
    };
    return {
        ltres: pick('SOULFONT_TRACE_LTRES', scale),
        qtres: pick('SOULFONT_TRACE_QTRES', scale),
        strokewidth: 0.5,
        pathomit: pick('SOULFONT_TRACE_PATH_OMIT', Math.round(8 * scale)),
        // blurradius is capped at 5 by ImageTracer.
        blurradius: Math.min(5, pick('SOULFONT_TRACE_BLUR_RADIUS', Math.round(scale))),
        blurdelta: pick('SOULFONT_TRACE_BLUR_DELTA', 64),
        pal: [{ r: 0, g: 0, b: 0, a: 255 }, { r: 255, g: 255, b: 255, a: 255 }],
        linefilter: true,
    };
}

function traceOne(pngPath, svgPath, option) {
    const png = PNG.sync.read(fs.readFileSync(pngPath));
    const imageData = { width: png.width, height: png.height, data: png.data };
    fs.writeFileSync(svgPath, ImageTracer.imagedataToSVG(imageData, option));
}

// ---------------------------------------------------------------------------
// Worker entry point: trace an assigned slice of the glyph list.
// ---------------------------------------------------------------------------
if (!isMainThread && workerData && workerData.role === 'tracer') {
    const { files, flippedDir, svgDir, option } = workerData;
    for (const file of files) {
        const fileName = path.basename(file, '.png');
        traceOne(path.join(flippedDir, file), path.join(svgDir, `${fileName}.svg`), option);
    }
    parentPort.postMessage(files.length);
    return;
}

const svg2ttf = require('svg2ttf');
const SVGIcons2SVGFontStream = require('svgicons2svgfont').default || require('svgicons2svgfont');

const userId = process.argv[2];
if (!userId) {
    console.error('Usage: node generateTTF.js <userId> [inputDir] [fontName]');
    process.exit(1);
}

// Optional args let us build several weights from the same user: each weight's glyph
// PNGs live in their own input dir and produce a separately-named TTF.
const inputDirName = process.argv[3] || 'flipped_result';
const fontName = process.argv[4] || `user_font_${userId}`;

// Per-font working directory.
const baseDir = path.join(__dirname, '..', 'workdir', 'fonts', userId.toString());
const flippedDir = path.join(baseDir, inputDirName);
// SVG scratch dirs are namespaced per font name so concurrent/repeat runs don't clash.
const svgDir = path.join(baseDir, 'svg', fontName);
const svgFontsDir = path.join(baseDir, 'svg_fonts');
const ttfDir = path.join(baseDir, 'ttf_fonts');

[baseDir, flippedDir, svgDir, svgFontsDir, ttfDir].forEach(dir => {
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
});

// Sorted so the glyph order in the font is stable between runs.
const files = fs.readdirSync(flippedDir).filter(f => f.endsWith('.png')).sort();
if (!files.length) {
    console.error(`No glyph PNGs found in ${flippedDir}`);
    process.exit(1);
}

const probe = PNG.sync.read(fs.readFileSync(path.join(flippedDir, files[0])));
const option = buildTraceOptions(probe.width);

// Tracing is pure CPU work per glyph, so a full Hangul set (11k+ glyphs) is worth
// spreading across cores; below that the thread startup cost outweighs the gain.
const PARALLEL_MIN_GLYPHS = 64;
const workerCount = Math.max(1, Math.min(8, (os.cpus() || { length: 1 }).length - 1));

function traceInline() {
    for (const file of files) {
        const fileName = path.basename(file, '.png');
        traceOne(path.join(flippedDir, file), path.join(svgDir, `${fileName}.svg`), option);
    }
}

function traceParallel() {
    // Round-robin so every worker gets a mix of simple and complex glyphs.
    const chunks = Array.from({ length: workerCount }, () => []);
    files.forEach((file, i) => chunks[i % workerCount].push(file));

    return Promise.all(chunks.filter(c => c.length).map(chunk => new Promise((resolve, reject) => {
        const worker = new Worker(__filename, {
            workerData: { role: 'tracer', files: chunk, flippedDir, svgDir, option },
        });
        worker.on('message', resolve);
        worker.on('error', reject);
        worker.on('exit', code => {
            if (code !== 0) reject(new Error(`Tracer worker exited with code ${code}`));
        });
    })));
}

async function traceAll() {
    if (files.length < PARALLEL_MIN_GLYPHS || workerCount === 1) {
        traceInline();
        return;
    }
    await traceParallel();
}

async function generateFont() {
    // PNG -> SVG
    const startedAt = Date.now();
    await traceAll();
    console.log(
        `Traced ${files.length} glyphs at ${probe.width}px ` +
        `(ltres=${option.ltres}, qtres=${option.qtres}, pathomit=${option.pathomit}) ` +
        `in ${((Date.now() - startedAt) / 1000).toFixed(1)}s`
    );

    // SVG font stream
    const fontStream = new SVGIcons2SVGFontStream({
        fontName: fontName,
        normalize: true,
        fontHeight: 1000,
        centerHorizontally: true,
        centerVertically: true,
        descent: 200,
    });

    const svgFontPath = path.join(svgFontsDir, `${fontName}_temp.svg`);
    const ttfOutputPath = path.join(ttfDir, `${fontName}.ttf`);

    const writeStream = fs.createWriteStream(svgFontPath);
    fontStream.pipe(writeStream);

    for (const file of files) {
        const fileName = path.basename(file, '.png');
        const svgPath = path.join(svgDir, `${fileName}.svg`);

        let codePoint = 0x20; // default: space
        const match = fileName.match(/inferred_(.+)/);
        if (match) {
            const hexStr = match[1];
            codePoint = parseInt(hexStr, 16);
            if (isNaN(codePoint)) codePoint = 0x20;
        }

        const glyphStream = fs.createReadStream(svgPath);
        glyphStream.metadata = {
            unicode: [String.fromCodePoint(codePoint)],
            name: `uni${codePoint.toString(16).toUpperCase()}`
        };

        fontStream.write(glyphStream);
    }

    fontStream.end();

    writeStream.on('finish', () => {
        try {
            // SVG font -> glyph TTF. Outline metrics (spacing, baseline, space glyph) are
            // applied afterwards by refine_metrics.py, and name-table / OS-2 metadata
            // (incl. the Korean family name) by set_font_metadata.py — fonttools is far
            // more reliable than opentype.js for Hangul.
            const svgFontData = fs.readFileSync(svgFontPath, 'utf8');
            const ttf = svg2ttf(svgFontData, {});
            fs.writeFileSync(ttfOutputPath, Buffer.from(ttf.buffer));
            console.log(`TTF font generated at: ${ttfOutputPath}`);

            fs.unlinkSync(svgFontPath);
            console.log(`Cleaned up temporary SVG font file: ${svgFontPath}`);
        } catch (err) {
            console.error('❌ Error during TTF generation:', err);
            process.exitCode = 1;
        }
    });

    writeStream.on('error', (err) => {
        console.error('Error writing SVG font:', err);
        process.exitCode = 1;
    });
}

generateFont().catch(err => {
    console.error('❌ Error during font generation:', err);
    process.exitCode = 1;
});
