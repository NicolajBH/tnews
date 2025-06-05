def analyse_errors [] {
  print "🔍 Analyzing errors in application logs..."
  open logs/api_log.log
  | lines
  | where ($it | str contains '"level": "ERROR"') or ($it | str contains '"levelname": "ERROR"')
  | each { |line| 
    try {
      $line | from json
    } catch {
    {raw_line: $line, parse_error: true}
    }
  }
  | where parse_error? != true
  | select timestamp level logger message error_type? error?
  | sort-by timestamp
  | print
}

def analyse_performance [--threshold: int = 1000] {
  print $"🚀 Finding operations slower than ($threshold)ms..."

  open logs/api_log.log
  | lines
  | where ($it | str contains 'duration_ms')
  | each { |line| 
  try {
    $line | from json
    } catch {
      null
    }
  }
  | where $it != null
  | where duration_ms? != null
  | where ($it.duration_ms | into float) > $threshold
  | select timestamp message duration_ms operation? logger
  | sort-by duration_ms -r
  | first 10
  | print
}

def analyse_requests [] {
  print "📊 Analyzing HTTP request patterns..."

  open logs/api_log.log
  | lines
  | where ($it | str contains 'Request completed') or ($it | str contains 'Request received')
  | each { |line|
    try {
      $line | from json
    } catch {
      null
    }
  }
  | where $it != null
  | group-by {|row| $row.path? | default "unknown"}
  | transpose endpoint requests
  | insert count {|row| $row.requests | length}
  | insert avg_duration {|row|
    $row.requests
    | where duration_ms? != null
    | get duration_ms
    | into float
    | math avg
  }
  | select endpoint count avg_duration
  | sort-by count -r
  | print
}

def analyse_health [] {
  print "🏥 Analyzing service health and circuit breaker events..."

  let circuit_events = (
    open logs/api_log.log
    | lines
    | where ($it | str downcase | str contains 'switching')
    | each { |line|
      try {
        $line | from json
      } catch {
        null
      }
    }
    | where $it != null
    | where ($it.state? != null) and ($it.state? != 'closed')
    | select task_id message circuit_name? state? logger
  )

  let health_events = (
    open logs/api_log.log
    | lines
    | where ($it | str downcase | str contains 'health')
    | each { |line|
      try {
        $line | from json
      } catch {
        null
      }
    }
    | where $it != null
    | where ($it.failure_count? != null) and ($it.failure_count > 1)
    | select task_id message service? logger failure_count?
  )

  print "Circuit Breaker Events:"
  $circuit_events | print
  print "\nHealth Events:"
  $health_events | print
}

def analyse_db [] {
  print "🗄️ Analyzing database operations..."

  open logs/api_log.log
  | lines
  | where ($it | str downcase | str contains 'database')
  | each { |line| 
    try {
      $line | from json
    } catch {
      null
    }
  }
  | where $it != null
  | select timestamp message error? error_type? logger
  | sort-by timestamp
  | print
}

def analyse_feeds [] {
  print "📰 Analyzing news feed processing..."

  open logs/api_log.log
  | lines
  | where ($it | str downcase | str contains 'feed')
  | each { |line| 
    try {
      $line | from json
    } catch {
      null
    }
  }
  | where $it != null
  | where ($it.message | str contains 'fetch') or ($it.message | str contains 'process') or ($it.message | str contains 'parse')
  | select timestamp message source_name? feed_name? article_count? duration_ms? logger
  | sort-by timestamp
  | first 10
  | print
}

def analyse_rate_limits [] {
  print "🚦 Analyzing rate limiting events..."

  open logs/api_log.log
  | lines
  | where ($it | str downcase | str contains 'rate limit')
  | each { |line| 
    try {
      $line | from json 
    } catch {
      null
    }
  }
  | where $it != null
  | select timestamp message logger client_ip? endpoint?
  | sort-by timestamp
  | print
}

def log_summary [] {
  print $"📈 Log Summary..."

  let all_logs = (
    open logs/api_log.log
    | lines
    | where ($it | str starts-with "{")
    | each { |line| 
      try {
        $line | from json
      } catch {
        {raw_line: $line, parse_error: true}
      }
    }
    | where parse_error? != true
  )

  let total_logs = ($all_logs | length)
  let error_count = ($all_logs | where level? == "ERROR" or levelname? == "ERROR" | length)
  let warning_count = ($all_logs | where level? == "WARNING" or levelname? == "WARNING" | length)
  let info_count = ($all_logs | where level? == "INFO" or levelname? == "INFO" | length)

  print $"Total log entries: ($total_logs)"
  print $"Errors: ($error_count)"
  print $"Warnings: ($warning_count)"
  print $"Info: ($info_count)"

  print "\nTop error types:"
  $all_logs
  | where level? == "ERROR" or levelname? == "ERROR"
  | where error_type? != null
  | group-by error_type
  | transpose error_type occurences
  | insert count {|row| $row.occurences | length}
  | select error_type count
  | sort-by count -r
  | first 5
  | print
}

def main [] {
  print "🚀 News Aggregation Service Log Analysis"
  print "========================================="

  log_summary
  print "\n"
  analyse_errors 
  print "\n"
  analyse_performance --threshold 500
  print "\n"
  analyse_requests 
  print "\n"
  analyse_health
  print "\n"
  analyse_feeds 
  print "\n"
  analyse_rate_limits
  print "\n"
}


export def "log errors" [] { analyse_errors }
export def "log performance" [] { analyse_performance }
export def "log requests" [] { analyse_requests }
export def "log health" [] { analyse_health }
export def "log database" [] { analyse_db }
export def "log feeds" [] { analyse_feeds }
export def "log rates" [] { analyse_rate_limits }
export def "log summary" [] { log_summary }
