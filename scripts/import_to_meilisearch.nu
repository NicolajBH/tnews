def format_times [pubDate] {
  let dt_local = $pubDate | into datetime --timezone UTC | date to-timezone local
  let formatted_date = $dt_local | format date "%B %e, %Y %l:%M %p"
  let tz_offset = $dt_local | format date "%z"
  let tz_hours = $tz_offset | str substring 1,3 | into int
  let tz_sign = if $tz_hours >= 0 { "+" } else { "-" }
  let tz_formatted = $"GMT($tz_sign)($tz_hours | math abs)"
  let feed_time = $dt_local | format date "%H:%M"
  let formatted_pubDate = $"($formatted_date) ($tz_formatted)"
  
  {
    formatted_pubDate: $formatted_pubDate,
    feed_time: $feed_time
  }
}

def import-to-meilisearch [] {
  print "Fetching articles from db..."
  let articles = (
    open database.db | query db "
    SELECT
    a.id,
    a.title,
    a.pub_date,
    s.feed_symbol,
    s.display_name as display_name,
    a.description,
    a.author_name,
    a.original_url
    FROM articles a
    JOIN sources s on a.source_name = s.name
    "
  )
  print $"Found ($articles | length) articles"
  
  let documents = ($articles | each { |row|
    # Call format_times and destructure the result
    let time_data = (format_times $row.pub_date)
    
    {
      id: $row.id,
      title: $row.title,
      pubDate: $row.pub_date,
      feed_symbol: $row.feed_symbol,
      display_name: $row.display_name,  
      formatted_pubDate: $time_data.formatted_pubDate,
      feed_time: $time_data.feed_time,
      description: ($row.description | default ""),
      author_name: ($row.author_name | default ""),
      url: $row.original_url,
    } 
  })
  
  print "Sending to Meilisearch..."
  let response = (http post --content-type application/json http://localhost:7700/indexes/articles/documents $documents)
  print $"Import response: ($response)"
  print $"Successfully imported ($documents | length) articles to Meilisearch"
}

import-to-meilisearch
