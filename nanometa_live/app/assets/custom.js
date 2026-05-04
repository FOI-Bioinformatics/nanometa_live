/**
 * Custom JavaScript for Nanometa Live dashboard.
 *
 * Handles toast dismissal and other UI interactions that are
 * better done client-side for immediate response.
 */

// Toast close button handler
document.addEventListener('click', function(event) {
    // Check if clicked element or its parent is a toast close button
    var target = event.target;
    var closeButton = target.closest('[data-dismiss="toast"]');

    if (closeButton) {
        // Find the parent toast notification
        var toast = closeButton.closest('.toast-notification');
        if (toast) {
            // Add fade-out class and remove after animation
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            setTimeout(function() {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 300);
        }
    }
});

// Auto-dismiss toasts after animation completes (4s delay + 0.5s fade)
var toastObserver = new MutationObserver(function(mutations) {
    mutations.forEach(function(mutation) {
        mutation.addedNodes.forEach(function(node) {
            if (node.classList && node.classList.contains('toast-notification')) {
                setTimeout(function() {
                    if (node.parentNode) {
                        node.parentNode.removeChild(node);
                    }
                }, 5000);
            }
        });
    });
});

// Start observing toast container when it exists
function observeToasts() {
    var container = document.getElementById('toast-container');
    if (container) {
        toastObserver.observe(container, {childList: true});
    } else {
        setTimeout(observeToasts, 500);
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', observeToasts);
} else {
    observeToasts();
}

// Keyboard accessibility for toast close
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        // Close all visible toasts on Escape
        var toasts = document.querySelectorAll('.toast-notification');
        toasts.forEach(function(toast) {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            setTimeout(function() {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 300);
        });
    }
});

/**
 * Sankey label repositioning.
 *
 * Plotly does not support per-node label alignment (plotly.js#7445).
 * This observer watches for Sankey SVG renders and places:
 *   - Leftmost column labels to the RIGHT of nodes
 *   - All other column labels to the LEFT of nodes
 */
(function() {
    function repositionSankeyLabels(container) {
        var sankey = container.querySelector('.sankey');
        if (!sankey) return;

        var nodeEls = sankey.querySelectorAll('.sankey-node');
        if (!nodeEls.length) return;

        var minX = Infinity;
        var maxX = -Infinity;
        var nodeData = [];
        nodeEls.forEach(function(n) {
            var t = n.getAttribute('transform') || '';
            var parts = t.replace('translate(', '').replace(')', '').split(',');
            var x = parseFloat(parts[0]) || 0;
            var rect = n.querySelector('.node-rect');
            var label = n.querySelector('.node-label');
            var w = rect ? (parseFloat(rect.getAttribute('width')) || 18) : 18;
            // Only consider nodes with visible labels for min/max
            var hasLabel = label && label.textContent;
            nodeData.push({x: x, w: w, label: label, hasLabel: !!hasLabel});
            if (hasLabel) {
                if (x < minX) minX = x;
                if (x > maxX) maxX = x;
            }
        });

        var leftThreshold = minX + 5;
        var rightThreshold = maxX - 5;

        nodeData.forEach(function(nd) {
            if (!nd.label || !nd.label.textContent) return;
            if (nd.x <= leftThreshold || nd.x >= rightThreshold) {
                // Leftmost and rightmost columns: label RIGHT of node
                nd.label.setAttribute('x', nd.w + 4);
                nd.label.setAttribute('text-anchor', 'start');
            } else {
                // Middle columns: label LEFT of node
                nd.label.setAttribute('x', -4);
                nd.label.setAttribute('text-anchor', 'end');
            }
        });
    }

    // Observe the classification plot for Sankey renders
    var observer = new MutationObserver(function(mutations) {
        var plotDiv = document.getElementById('classification-plot');
        if (!plotDiv) return;
        // Debounce: reposition after DOM settles
        clearTimeout(observer._timer);
        observer._timer = setTimeout(function() {
            repositionSankeyLabels(plotDiv);
        }, 150);
    });

    // Start observing once the DOM is ready
    function startObserving() {
        var plotDiv = document.getElementById('classification-plot');
        if (plotDiv) {
            observer.observe(plotDiv, {childList: true, subtree: true});
        } else {
            // Retry until the element exists
            setTimeout(startObserving, 500);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startObserving);
    } else {
        startObserving();
    }
})();
