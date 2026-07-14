package router

import (
	"embed"
	"io/fs"
	"net/http"
	"strings"
)

//go:embed static/*
var demoStatic embed.FS

func withCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		if req.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, req)
	})
}

func (rt *Router) handleDemo(w http.ResponseWriter, req *http.Request) {
	if req.Method != http.MethodGet && req.Method != http.MethodHead {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	path := strings.TrimPrefix(req.URL.Path, "/demo")
	if path == "" || path == "/" {
		path = "index.html"
	} else {
		path = strings.TrimPrefix(path, "/")
	}

	data, err := fs.ReadFile(demoStatic, "static/"+path)
	if err != nil {
		// Fallback: bare /demo and unknown paths serve the console.
		data, err = fs.ReadFile(demoStatic, "static/index.html")
		if err != nil {
			http.NotFound(w, req)
			return
		}
		path = "index.html"
	}

	ctype := "text/html; charset=utf-8"
	if strings.HasSuffix(path, ".js") {
		ctype = "application/javascript; charset=utf-8"
	} else if strings.HasSuffix(path, ".css") {
		ctype = "text/css; charset=utf-8"
	} else if strings.HasSuffix(path, ".json") {
		ctype = "application/json; charset=utf-8"
	} else if strings.HasSuffix(path, ".svg") {
		ctype = "image/svg+xml"
	}
	w.Header().Set("Content-Type", ctype)
	w.Header().Set("Cache-Control", "no-store")
	if req.Method == http.MethodHead {
		return
	}
	_, _ = w.Write(data)
}

func (rt *Router) handleDemoRedirect(w http.ResponseWriter, req *http.Request) {
	if req.URL.Path != "/" {
		http.NotFound(w, req)
		return
	}
	http.Redirect(w, req, "/demo/", http.StatusFound)
}
