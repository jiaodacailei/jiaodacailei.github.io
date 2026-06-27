(function () {
  const script = document.currentScript;
  const base = (script && script.getAttribute('data-base')) || '../../images/';

  // w/h = desktop display size; aspect ratio tuned to each photo
  const PHOTOS = [
    { file: 'photo-1.jpg', w: 128, h: 170, pos: 'center 8%'    },
    { file: 'photo-2.jpg', w: 112, h: 186, pos: 'center 8%'    },
    { file: 'photo-3.jpg', w: 128, h: 170, pos: 'center 10%'   },
    { file: 'life-1.jpg',  w: 200, h: 150, pos: 'center center' },
    { file: 'life-2.jpg',  w: 112, h: 200, pos: 'center 12%'   },
  ];

  function init() {
    const p = PHOTOS[Math.floor(Math.random() * PHOTOS.length)];

    // On mobile (≤640px) scale down and sit just above the browser chrome
    const mobile = window.innerWidth <= 640;
    const scale  = mobile ? 0.72 : 1;
    const dw     = Math.round(p.w * scale);
    const dh     = Math.round(p.h * scale);
    const bottom = mobile ? '12px' : '88px';
    const right  = mobile ? '10px' : '20px';

    if (!document.getElementById('fp-style')) {
      const s = document.createElement('style');
      s.id = 'fp-style';
      s.textContent = `
        @keyframes fp-float {
          0%, 100% { transform: translateY(0px);
                     box-shadow: 0 8px 28px rgba(0,0,0,.22), 0 2px 6px rgba(0,0,0,.12); }
          50%       { transform: translateY(-10px);
                     box-shadow: 0 20px 52px rgba(0,0,0,.28), 0 6px 16px rgba(0,0,0,.14); }
        }
        .fp-card {
          animation: fp-float 4.5s ease-in-out infinite;
          transition: transform .2s, box-shadow .2s;
        }
        .fp-card:hover  { animation-play-state: paused; transform: scale(1.04) translateY(-4px); }
        .fp-card:active { animation-play-state: paused; transform: scale(0.97); }
        .fp-close {
          position: absolute; top: 6px; right: 6px;
          width: 22px; height: 22px; border-radius: 50%;
          background: rgba(0,0,0,.52); color: #fff; border: none;
          font-size: 15px; line-height: 1; cursor: pointer; padding: 0;
          display: flex; align-items: center; justify-content: center;
          transition: background .15s, transform .15s;
        }
        .fp-close:hover  { background: rgba(0,0,0,.78); transform: scale(1.15); }
        .fp-close:active { transform: scale(0.9); }
        .fp-label {
          position: absolute; bottom: 0; left: 0; right: 0;
          background: linear-gradient(transparent, rgba(0,0,0,.58));
          color: #fff; font-size: 11px; font-weight: 700;
          padding: 20px 8px 7px; letter-spacing: .05em;
          font-family: -apple-system, 'Noto Sans SC', sans-serif;
        }
      `;
      document.head.appendChild(s);
    }

    const card = document.createElement('div');
    card.className = 'fp-card';
    Object.assign(card.style, {
      position:     'fixed',
      right:        right,
      bottom:       bottom,
      zIndex:       '55',
      borderRadius: '12px',
      overflow:     'hidden',
      width:        dw + 'px',
      background:   '#fff',
      cursor:       'default',
    });

    const img = document.createElement('img');
    img.src = base + p.file;
    img.alt = '蔡磊';
    Object.assign(img.style, {
      display:        'block',
      width:          dw + 'px',
      height:         dh + 'px',
      objectFit:      'cover',
      objectPosition: p.pos,
    });

    const label = document.createElement('div');
    label.className = 'fp-label';
    label.textContent = '📸 蔡磊';

    const close = document.createElement('button');
    close.className = 'fp-close';
    close.innerHTML  = '×';
    close.title      = '关闭';
    close.onclick    = () => card.remove();

    card.appendChild(img);
    card.appendChild(label);
    card.appendChild(close);
    document.body.appendChild(card);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
